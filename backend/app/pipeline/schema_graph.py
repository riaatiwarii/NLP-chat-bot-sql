import networkx as nx
from sentence_transformers import SentenceTransformer, util
from app.config import config

class SchemaGraph:
    """
    Stage 6: Schema Linking & NetworkX Schema Graph
    Builds a NetworkX graph of database tables (nodes) and foreign key relationships (edges).
    Computes vector embeddings for schema elements to perform top-k relevant sub-graph retrieval.
    """
    def __init__(self, tables_schema: dict, fk_edges: list[tuple] = None, embedder: SentenceTransformer = None):
        self.tables_schema = tables_schema or {} # {"table_name": [{"name": col, "type": type}, ...]}
        self.fk_edges = fk_edges or [] # [("tableA", "tableB", {"fk": "colA=colB"}), ...]
        self.embedder = embedder
        
        self.graph = nx.Graph()
        self.schema_embeddings = []
        self.schema_nodes = []
        self._build_graph()

    def _build_graph(self):
        """Constructs NetworkX schema graph."""
        table_descriptions = {
            "AlertsDetails": "Primary telemetry table for active security alerts, incident events, status, severity, zone, area, location, timestamps, and responder status.",
            "AlertHistory": "Historical telemetry log of all alert actions, status changes, updates, user remarks, and timestamps.",
            "AlertAttachment": "Uploaded image and video attachment files linked to security alerts.",
            "AlertSubtype": "Master directory of alert subtypes, classifications, categories, and descriptions.",
            "AlertTypes": "Master directory of main alert types, categories, and severity levels.",
            "CameraList": "CCTV surveillance camera directory, camera names, locations, areas, and online/offline status.",
            "Jurisdiction_mstr": "Master table of police jurisdictions, boundaries, and regional control centers.",
            "RawAttachments": "Raw attachment file uploads and media metadata.",
            "Sensor_Master": "Directory of hardware IoT sensors, sensor types, locations, and operational status.",
            "Junction_mstr": "Master directory of traffic junctions, intersections, areas, and location details."
        }
        for table_name, cols in self.tables_schema.items():
            col_names = [c["name"] if isinstance(c, dict) else str(c) for c in cols]
            domain_desc = table_descriptions.get(table_name, f"Database table {table_name}")
            desc = f"Table: {table_name}. Purpose: {domain_desc}. Columns: {', '.join(col_names)}"
            self.graph.add_node(table_name, type="table", description=desc, columns=cols)
            self.schema_nodes.append((table_name, desc))

        for u, v, data in self.fk_edges:
            if u in self.graph and v in self.graph:
                self.graph.add_edge(u, v, **data)

        # Precompute dense embeddings for schema nodes
        if self.embedder and self.schema_nodes:
            try:
                descriptions = [desc for _, desc in self.schema_nodes]
                embeddings_tensor = self.embedder.encode(descriptions, convert_to_tensor=True)
                self.schema_embeddings = embeddings_tensor
            except Exception as e:
                print(f"[SCHEMA GRAPH WARNING] Vector index build failed: {e}")

    def get_relevant_schema_subset(self, query: str, top_k: int = None) -> dict:
        """
        Embeds query and retrieves top-k relevant tables and their connected join paths in NetworkX graph.
        Returns subset schema dict: {"tables": {table_name: cols}, "join_paths": [...]}
        """
        k = top_k or config.SCHEMA_LINKER_TOP_K
        if not self.tables_schema:
            return {"tables": {}, "join_paths": []}

        selected_tables = set()

        # Keyword-based domain priority boost with HARD PRIORITY for vw_AlertReporting / AlertsDetails
        q_lower = query.lower()
        if any(w in q_lower for w in ["branch", "branches", "lho", "lhos", "alert", "alerts", "dashboard", "summary", "report", "telemetry"]):
            # Hard lock to vw_AlertReporting to prevent Sensor_Master or Jurisdiction_mstr lexical interference
            target_tbl = "vw_AlertReporting" if "vw_AlertReporting" in self.tables_schema else "AlertsDetails"
            if target_tbl in self.tables_schema:
                subset_tables = {target_tbl: self.tables_schema[target_tbl]}
                return {"tables": subset_tables, "join_paths": []}

        priority_boost = []
        if "incident" in q_lower:
            priority_boost.extend(["Incident_Data", "IncidentHistory"])
        if any(w in q_lower for w in ["camera", "cctv", "recording"]):
            priority_boost.extend(["CameraList", "Master_CamDetails"])

        for p_tbl in priority_boost:
            if p_tbl in self.tables_schema:
                selected_tables.add(p_tbl)

        if self.embedder and self.schema_embeddings is not None and len(self.schema_embeddings) > 0:
            try:
                query_emb = self.embedder.encode(query, convert_to_tensor=True)
                scores = util.cos_sim(query_emb, self.schema_embeddings)[0]
                
                # Filter tables exceeding similarity threshold
                for idx, score in enumerate(scores):
                    if float(score) >= config.SCHEMA_LINKER_SIMILARITY_THRESHOLD:
                        selected_tables.add(self.schema_nodes[idx][0])

                # Top-k fallback if threshold yielded fewer
                if len(selected_tables) == 0:
                    top_indices = scores.argsort(descending=True)[:k]
                    for idx in top_indices:
                        selected_tables.add(self.schema_nodes[int(idx)][0])
            except Exception as e:
                print(f"[SCHEMA GRAPH WARNING] Search failed: {e}")
                selected_tables = set(list(self.tables_schema.keys())[:k])
        else:
            selected_tables = set(list(self.tables_schema.keys())[:k])

        # Compute connected sub-graph join paths using NetworkX
        join_paths = []
        selected_list = list(selected_tables)
        for i in range(len(selected_list)):
            for j in range(i + 1, len(selected_list)):
                u, v = selected_list[i], selected_list[j]
                if nx.has_path(self.graph, u, v):
                    try:
                        path = nx.shortest_path(self.graph, u, v)
                        if len(path) > 1:
                            join_paths.append(" -> ".join(path))
                    except Exception:
                        pass

        # Build schema subset
        subset_tables = {t: self.tables_schema[t] for t in selected_tables if t in self.tables_schema}

        return {
            "tables": subset_tables,
            "join_paths": list(set(join_paths))
        }

    def validate_plan_schema(self, tables_needed: list[str], columns_referenced: list[tuple[str, str]]) -> tuple[bool, str]:
        """
        Validates referenced tables and columns exist in schema graph and join paths are valid.
        """
        for t in tables_needed:
            if t not in self.graph:
                return False, f"Table '{t}' does not exist in schema graph."

        for t, c in columns_referenced:
            if t in self.tables_schema:
                col_names = [col["name"] if isinstance(col, dict) else str(col) for col in self.tables_schema[t]]
                if c not in col_names and c != "*":
                    return False, f"Column '{c}' does not exist in table '{t}'."

        # Check connectivity if multiple tables needed
        if len(tables_needed) > 1:
            for i in range(len(tables_needed) - 1):
                u, v = tables_needed[i], tables_needed[i+1]
                if not nx.has_path(self.graph, u, v):
                    # Check if any path exists overall
                    has_any = any(nx.has_path(self.graph, u, other) for other in tables_needed if other != u)
                    if not has_any:
                        return False, f"No join relationship path found between table '{u}' and table '{v}' in schema graph."

        return True, "Valid"
