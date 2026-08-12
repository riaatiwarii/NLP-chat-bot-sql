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
        Links a natural language query to the introspected database schema and categorical values.
        
        Returns:
            dict containing:
                - "relevant_tables": set of matching table names
                - "relevant_columns": list of matched column dicts with similarity scores
                - "grounded_values": dict mapping query terms to (column_name, exact_db_value)
                - "focused_schema_prompt": concise markdown schema containing only linked elements
        """
        if not self.schema_engine or not self.schema_engine.schema_vector_index or not self.schema_engine.embedder:
            return {
                "relevant_tables": set(),
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
        matched_tables = set()

        for idx, score in enumerate(sim_scores):
            score_val = float(score)
            item = index[idx]
            if score_val >= similarity_threshold:
                matched_tables.add(item["table_name"])
                if item["type"] == "column":
                    matched_columns.append({
                        "table_name": item["table_name"],
                        "column_name": item["column_name"],
                        "score": round(score_val, 4),
                        "text": item["text"]
                    })

        # Sort columns by highest semantic similarity score
        matched_columns.sort(key=lambda x: x["score"], reverse=True)
        top_columns = matched_columns[:top_k_columns]

        # 3. Categorical Value Grounding (Entity Alignment)
        grounded_values = self._ground_categorical_values(query_text)

        # 4. Construct a Focused Schema Prompt tailored specifically to the linked schema elements
        focused_prompt = self._build_focused_schema_prompt(matched_tables, top_columns, grounded_values)

        return {
            "relevant_tables": list(matched_tables),
            "relevant_columns": top_columns,
            "grounded_values": grounded_values,
            "focused_schema_prompt": focused_prompt
        }

    def _ground_categorical_values(self, query_text):
        """
        Scans cached distinct text values from database columns to ground 
        user entity terms (e.g., 'nariman point', 'offline', 'panic button') 
        to exact database string literals.
        """
        grounded = {}
        query_lower = query_text.lower()
        clean_query_words = set(re.findall(r'\w+', query_lower))

        column_values = self.schema_engine.column_values_cache if self.schema_engine else {}

        for col_key, samples in column_values.items():
            table_name, col_name = col_key.split(".", 1)
            for sample in samples:
                sample_str = str(sample).strip()
                sample_lower = sample_str.lower()
                
                # Check for exact substring match or word boundary overlap
                # Check exact substring, query phrase in sample, or word intersection
                sample_words = set(re.findall(r'\w+', sample_lower)) - {'sbi', 'ao', 'branch', 'the', 'of', 'and', 'in'}
                query_meaningful_words = clean_query_words - {'sbi', 'ao', 'branch', 'the', 'of', 'and', 'in', 'show', 'which', 'are', 'is', 'for', 'all'}
                
                common_words = sample_words.intersection(query_meaningful_words)
                
                if (sample_lower in query_lower or any(w in query_lower for w in sample_lower.split() if len(w) > 4)) and len(sample_str) > 2:
                    grounded[sample_str] = {
                        "table_name": table_name,
                        "column_name": col_name,
                        "db_value": sample_str,
                        "match_type": "substring_match"
                    }
                elif len(common_words) >= 1 and (len(sample_words) <= len(common_words) or len(common_words) >= 2):
                    grounded[sample_str] = {
                        "table_name": table_name,
                        "column_name": col_name,
                        "db_value": sample_str,
                        "match_type": "word_set_match"
                    }

        return grounded


    def _build_focused_schema_prompt(self, matched_tables, matched_columns, grounded_values):
        """
        Formats a focused schema prompt incorporating semantically linked columns 
        and grounded value hints to guide LLM SQL generation.
        """
        full_schema = self.schema_engine.tables_schema if self.schema_engine else {}
        if not full_schema:
            return ""

        lines = ["Database Schema & Linked Semantic Hints:\n"]

        target_tables = matched_tables if matched_tables else full_schema.keys()
        idx = 1
        for table_name in target_tables:
            if table_name not in full_schema:
                continue
            table_data = full_schema[table_name]
            lines.append(f"{idx}. Table '{table_name}':")
            for col in table_data["columns"]:
                pk_str = " [PRIMARY KEY]" if col["primary_key"] else ""
                samples = f" (samples: {', '.join(col['sample_values'])})" if col['sample_values'] else ""
                lines.append(f"   - {col['name']} ({col['type']}){pk_str}{samples}")
            lines.append("")
            idx += 1

        if grounded_values:
            lines.append("Grounded Entity Value Literal Hints (Use exact string in WHERE clauses):")
            for user_term, info in grounded_values.items():
                lines.append(f"   - Match: Column '{info['table_name']}.{info['column_name']}' contains value '{info['db_value']}'")
            lines.append("")

        return "\n".join(lines)
