import re
import numpy as np
from sentence_transformers import util

class SchemaLinker:
    """
    Semantic Schema Linker & Categorical Value Grounder.
    Maps natural language user queries to target database tables, columns, 
    and distinct categorical values using dense vector cosine similarity 
    and fuzzy entity matching.
    """

    def __init__(self, schema_engine):
        self.schema_engine = schema_engine

    def link_schema_and_values(self, query_text, top_k_columns=6, similarity_threshold=0.20):
        """
        Links a natural language query to the introspected database schema graph.
        
        Selection Process:
        1. Identifies initial tables clearing the similarity threshold (>= 0.35).
        2. Schema Graph Expansion: Pulls in any table directly connected via Foreign Key (1-hop FK hop)
           to the selected tables, even if it didn't independently clear the 0.35 threshold.
        3. Generates full column list with descriptions and FK edges for prompt injection.
        """
        if not self.schema_engine or not self.schema_engine.schema_vector_index or not self.schema_engine.embedder:
            return {
                "relevant_tables": [],
                "expanded_tables": [],
                "relevant_columns": [],
                "grounded_values": {},
                "focused_schema_prompt": self.schema_engine.generate_dynamic_schema_prompt() if self.schema_engine else ""
            }

        # 1. Encode user query text
        query_embedding = self.schema_engine.embedder.encode(query_text, convert_to_tensor=True, show_progress_bar=False)

        # 2. Compute Cosine Similarity against all schema elements in index
        index = self.schema_engine.schema_vector_index
        index_embeddings = [item["embedding"] for item in index]
        
        # Stack tensor embeddings
        if hasattr(index_embeddings[0], 'unsqueeze'):
            import torch
            embeddings_tensor = torch.stack(index_embeddings)
            sim_scores = util.cos_sim(query_embedding, embeddings_tensor)[0].cpu().numpy()
        else:
            sim_scores = np.dot(index_embeddings, query_embedding) / (
                np.linalg.norm(index_embeddings, axis=1) * np.linalg.norm(query_embedding)
            )

        matched_columns = []
        initial_tables = set()

        # Ignore internal staging/clone tables to prevent ambiguous table races
        IGNORED_STAGING_PATTERNS = ["_common", "_bly", "bly", "supdetails", "attachment", "apitable"]

        for idx, score in enumerate(sim_scores):
            score_val = float(score)
            item = index[idx]
            tbl_name = item["table_name"]
            
            # Exclude staging clones
            if any(pat in tbl_name.lower() for pat in IGNORED_STAGING_PATTERNS if tbl_name not in ["AlertsDetails", "Incident_Data", "CameraList", "Master_CamDetails"]):
                continue

            if score_val >= similarity_threshold:
                initial_tables.add(tbl_name)
                if item["type"] == "column":
                    matched_columns.append({
                        "table_name": tbl_name,
                        "column_name": item["column_name"],
                        "score": round(score_val, 4),
                        "text": item["text"]
                    })

        # Sort columns by highest semantic similarity score
        matched_columns.sort(key=lambda x: x["score"], reverse=True)
        top_columns = matched_columns[:top_k_columns]

        # 3. Schema Graph 1-Hop Foreign Key Expansion
        expanded_tables = set(initial_tables)
        fk_edges = getattr(self.schema_engine, "fk_edges", [])
        
        for table in initial_tables:
            for edge in fk_edges:
                if edge["source_table"] == table and edge["target_table"] in self.schema_engine.tables_schema:
                    expanded_tables.add(edge["target_table"])
                elif edge["target_table"] == table and edge["source_table"] in self.schema_engine.tables_schema:
                    expanded_tables.add(edge["source_table"])

        if expanded_tables != initial_tables:
            print(f"[SCHEMA GRAPH] Expanded tables from {initial_tables} to include 1-hop FK neighbors: {expanded_tables - initial_tables}")

        # 4. Categorical Value Grounding
        grounded_values = self._ground_categorical_values(query_text)

        # 5. Construct Focused Schema Prompt with Schema Graph (columns + descriptions + FK edges)
        focused_prompt = self._build_focused_schema_prompt(expanded_tables, top_columns, grounded_values, fk_edges)

        return {
            "relevant_tables": list(initial_tables),
            "expanded_tables": list(expanded_tables),
            "relevant_columns": top_columns,
            "grounded_values": grounded_values,
            "focused_schema_prompt": focused_prompt
        }

    def _ground_categorical_values(self, query_text):
        """
        Scans cached distinct text values from database columns to ground 
        user entity terms (e.g., 'nariman point', 'critical', 'closed', 'urgent') 
        to exact database string literals using direct matching + synonym mapping layer.
        Logs resolutions to backend/app/logs/value_grounding.jsonl.
        """
        grounded = {}
        query_lower = query_text.lower()
        clean_query_words = set(re.findall(r'\w+', query_lower))

        column_values = self.schema_engine.column_values_cache if self.schema_engine else {}

        # 1. Direct and Substring Matching over Cached DB Column Values
        for col_key, samples in column_values.items():
            table_name, col_name = col_key.split(".", 1)
            for sample in samples:
                sample_str = str(sample).strip()
                sample_lower = sample_str.lower()
                
                sample_words = set(re.findall(r'\w+', sample_lower)) - {'sbi', 'ao', 'branch', 'the', 'of', 'and', 'in'}
                query_meaningful_words = clean_query_words - {'sbi', 'ao', 'branch', 'the', 'of', 'and', 'in', 'show', 'which', 'are', 'is', 'for', 'all'}
                
                common_words = sample_words.intersection(query_meaningful_words)
                
                if (sample_lower in query_lower or any(w in query_lower for w in sample_lower.split() if len(w) > 4)) and len(sample_str) > 2:
                    grounded[sample_str] = {
                        "table_name": table_name,
                        "column_name": col_name,
                        "db_value": sample_str,
                        "match_type": "substring_match",
                        "confidence": 0.98
                    }
                elif len(common_words) >= 1 and (len(sample_words) <= len(common_words) or len(common_words) >= 2):
                    grounded[sample_str] = {
                        "table_name": table_name,
                        "column_name": col_name,
                        "db_value": sample_str,
                        "match_type": "word_set_match",
                        "confidence": 0.90
                    }

        # 2. Dynamic Synonym-to-Literal Mapping Layer for Categorical Columns
        # Built from real stored distinct values (Severity: Low, High, Medium; Status: Pending, Closed, Acknowledged)
        synonym_dictionary = {
            "severity": {
                "high": ["critical", "urgent", "severe", "p1", "emergency", "high"],
                "medium": ["moderate", "medium", "p2", "normal"],
                "low": ["minor", "low", "p3", "info"]
            },
            "status": {
                "closed": ["closed", "resolved", "done", "fixed", "completed"],
                "active": ["active", "live", "ongoing"],
                "pending": ["pending", "open", "unresolved", "new", "unhandled"],
                "acknowledged": ["acknowledged", "acked", "in progress", "assigned"]
            }
        }

        for word in clean_query_words:
            for cat_col, mapping in synonym_dictionary.items():
                for target_val, synonyms in mapping.items():
                    if word in synonyms:
                        for col_key, samples in column_values.items():
                            table_name, col_name = col_key.split(".", 1)
                            if cat_col in col_name.lower():
                                for sample in samples:
                                    sample_str = str(sample).strip()
                                    if sample_str.lower() == target_val:
                                        key_id = f"{word}->{sample_str}"
                                        grounded[key_id] = {
                                            "table_name": table_name,
                                            "column_name": col_name,
                                            "user_term": word,
                                            "db_value": sample_str,
                                            "match_type": "synonym_grounding",
                                            "confidence": 0.95
                                        }
                                        self._log_value_grounding(word, f"{table_name}.{col_name}", sample_str, 0.95)

        return grounded

    def _log_value_grounding(self, user_term: str, column_name: str, grounded_literal: str, confidence: float):
        """Logs value grounding resolutions to an audit log file."""
        import os, json
        from datetime import datetime
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "user_term": user_term,
            "column": column_name,
            "grounded_literal": grounded_literal,
            "confidence": confidence
        }
        print(f"[VALUE GROUNDING LOG] Term '{user_term}' -> {column_name} = '{grounded_literal}' (confidence: {confidence:.2f})")
        try:
            log_dir = os.path.join(os.path.dirname(__file__), "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, "value_grounding.jsonl")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[GROUNDING LOG WARNING] Failed to write log: {e}")

    def _build_focused_schema_prompt(self, expanded_tables, matched_columns, grounded_values, fk_edges=None):
        """
        Formats a focused schema prompt incorporating semantically linked columns, 
        1-line column descriptions, foreign key graph edges, and grounded value hints.
        """
        full_schema = self.schema_engine.tables_schema if self.schema_engine else {}
        if not full_schema:
            return ""

        lines = ["### Expanded Schema Graph (Selected Tables + 1-Hop Foreign Key Expansion):\n"]

        tables_to_include = expanded_tables if expanded_tables else full_schema.keys()
        idx = 1
        for table_name in tables_to_include:
            if table_name not in full_schema:
                continue
            table_data = full_schema[table_name]
            lines.append(f"{idx}. Table '{table_name}' (rows: {table_data.get('row_count', 0)}):")
            for col in table_data["columns"]:
                pk_str = " [PRIMARY KEY]" if col["primary_key"] else ""
                desc = f" - {col['description']}" if col.get('description') else ""
                samples = f" (samples: {', '.join(col['sample_values'])})" if col['sample_values'] else ""
                lines.append(f"   - {col['name']} ({col['type']}){pk_str}{desc}{samples}")
            lines.append("")
            idx += 1

        # Foreign Key Edges
        relevant_edges = []
        if fk_edges:
            for edge in fk_edges:
                if edge["source_table"] in tables_to_include and edge["target_table"] in tables_to_include:
                    relevant_edges.append(f"   - {edge['source_table']}.{edge['source_col']} <-> {edge['target_table']}.{edge['target_col']}")

        if relevant_edges:
            lines.append("Foreign Key Relationships (Graph Edges):")
            lines.extend(relevant_edges)
            lines.append("")

        if grounded_values:
            lines.append("Grounded Entity Value Literal Hints (Use exact string in WHERE clauses):")
            for user_term, info in grounded_values.items():
                lines.append(f"   - Match: Column '{info['table_name']}.{info['column_name']}' contains value '{info['db_value']}'")
            lines.append("")

        return "\n".join(lines)

