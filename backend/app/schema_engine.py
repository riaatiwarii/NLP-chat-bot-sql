import os
import json
import numpy as np
from sqlalchemy import inspect, text
from sentence_transformers import SentenceTransformer, util
from app.config import config

class SchemaEngine:
    """
    Dynamic Database Introspection & Schema Vector Indexer.
    Introspects tables, columns, data types, and distinct categorical values 
    from any connected SQLAlchemy engine (SQL Server, SQLite, PostgreSQL, etc.)
    and computes dense semantic vector embeddings using sentence-transformers (all-MiniLM-L6-v2).
    """

    def __init__(self, engine=None, model_name="all-MiniLM-L6-v2"):
        self.engine = engine
        self.model_name = model_name
        self.embedder = None
        self.tables_schema = {}
        self.column_values_cache = {}
        self.schema_vector_index = []  # List of dicts with text, metadata, embedding
        self.fk_edges = []
        self.inferred_column_descriptions = {}

        self._load_embedder()
        if self.engine is not None:
            self.introspect_database()

    def _load_embedder(self):
        """Loads sentence-transformers model for dense semantic embeddings."""
        try:
            print(f"[SCHEMA ENGINE] Loading semantic embedding model: '{self.model_name}'...")
            try:
                self.embedder = SentenceTransformer(self.model_name, local_files_only=True)
            except Exception:
                self.embedder = SentenceTransformer(self.model_name)
            print("[SCHEMA ENGINE] Semantic embedder loaded successfully.")
        except Exception as e:
            print(f"[SCHEMA ENGINE WARNING] Failed to load SentenceTransformer: {e}")
            self.embedder = None

    def introspect_database(self, engine=None):
        """
        Dynamically inspects tables, columns, data types, primary keys, 
        foreign key relationships, and distinct text sample values.
        """
        if engine:
            self.engine = engine
        if not self.engine:
            print("[SCHEMA ENGINE WARNING] No database engine provided for introspection.")
            return {}

        print("[SCHEMA ENGINE] Introspecting database schema & building schema graph...")
        inspector = inspect(self.engine)
        schema_info = {}
        column_values = {}
        self.inferred_column_descriptions = {}

        try:
            try:
                view_names = inspector.get_view_names()
            except Exception:
                view_names = []
            raw_table_names = inspector.get_table_names() + view_names
            # Strictly restrict table introspection to ALLOWED_TABLES
            allowed_set = set(config.ALLOWED_TABLES)
            table_names = [t for t in raw_table_names if t in allowed_set]
            if not table_names:
                table_names = list(allowed_set)
        except Exception as e:
            print(f"[SCHEMA ENGINE ERROR] Could not fetch table names: {e}")
            return {}

        is_small_schema = len(table_names) <= 30
        priority_tables = ["AlertsDetails", "vw_AlertReporting", "AlertAttachment", "RawAttachments", "Jurisdiction_mstr", "Junction_mstr", "Sensor_Master"]

        with self.engine.connect() as conn:
            for table_name in table_names:
                columns = inspector.get_columns(table_name)
                pk_constraint = inspector.get_pk_constraint(table_name)
                primary_keys = pk_constraint.get('constrained_columns', []) if pk_constraint else []

                is_priority = is_small_schema or (table_name in priority_tables)

                col_list = []
                for col in columns:
                    col_name = col['name']
                    col_type = str(col['type'])
                    is_pk = col_name in primary_keys

                    col_desc = self._get_column_description(table_name, col_name, col_type)

                    # Fetch sample values only for text columns in priority tables
                    distinct_samples = []
                    is_text_type = any(t in col_type.lower() for t in ['char', 'text', 'string', 'varchar', 'nvarchar'])
                    if is_text_type and is_priority and not any(k in col_name.lower() for k in ['id', 'uuid', 'password', 'key', 'guid']):
                        try:
                            query_str = f"SELECT DISTINCT TOP 10 [{col_name}] FROM (SELECT TOP 200 [{col_name}] FROM [{table_name}] WHERE [{col_name}] IS NOT NULL) AS sample_sub"
                            try:
                                res = conn.execute(text(query_str)).fetchall()
                            except Exception:
                                query_str_alt = f"SELECT DISTINCT [{col_name}] FROM (SELECT [{col_name}] FROM [{table_name}] WHERE [{col_name}] IS NOT NULL LIMIT 200) AS sample_sub"
                                res = conn.execute(text(query_str_alt)).fetchall()

                            distinct_samples = [str(r[0]).strip() for r in res if r[0] is not None and str(r[0]).strip()]

                            if distinct_samples:
                                col_key = f"{table_name}.{col_name}"
                                column_values[col_key] = distinct_samples
                        except Exception:
                            pass

                    col_list.append({
                        "name": col_name,
                        "type": col_type,
                        "primary_key": is_pk,
                        "description": col_desc,
                        "sample_values": distinct_samples[:5]
                    })

                schema_info[table_name] = {
                    "columns": col_list,
                    "row_count": self._get_table_row_count(conn, table_name) if is_priority else 0
                }

        self.tables_schema = schema_info
        self.column_values_cache = column_values

        # Introspect foreign key relationships (graph edges)
        self.fk_edges = self._introspect_foreign_keys(inspector, table_names)

        # Build dynamic vector embeddings for the introspected schema
        self._build_schema_vector_index()

        print(f"[SCHEMA ENGINE] Introspection complete. Discovered {len(schema_info)} tables & {len(self.fk_edges)} FK graph edges.")
        return schema_info

    def _get_column_description(self, table_name: str, col_name: str, col_type: str) -> str:
        """Infers a one-line semantic description per column based on domain heuristics."""
        col_lower = col_name.lower()

        if col_name in ["AlertID", "AlertId"]:
            return "Unique primary identifier for security alert record"
        elif col_name == "AlertType":
            return "Category type of security alert (Analytics, VMS, Camera Tampering, Tamper, Motion, Breach)"
        elif col_name in ["Area", "Location", "BranchName", "LocationName"]:
            return "Geographic branch, area, circle, site location name, or LHO office"
        elif col_name in ["Datetime", "IncidentTime", "CreatedTime", "AlertTime"]:
            return "Timestamp when alert or incident event was logged (Incident Datetime)"
        elif col_name in ["AckTime", "AcknowledgedTime"]:
            return "Operator incident response time acknowledgment timestamp (AckTime - Datetime delay)"
        elif col_name in ["ClosedTime", "ResolvedTime"]:
            return "Timestamp when alert or incident ticket was resolved and closed"
        elif col_name in ["Severity", "Priority"]:
            return "Priority severity level of alert (High, Medium, Low, Critical, Urgent, P1, P2)"
        elif col_name in ["Status", "IncidentStatus"]:
            return "Current operational state of alert or ticket (Pending, Acknowledged, Closed, Active, Resolved, Unhandled, Open)"
        elif col_name in ["IncidentId", "IncidentID", "TicketId"]:
            return "Unique numeric ticket identifier linking alerts to incidents"
        elif col_name in ["CameraId", "CameraID", "CamId"]:
            return "Unique identifier for CCTV camera device"
        elif col_name in ["CameraName", "CamName"]:
            return "Descriptive name or placement label of CCTV camera"
        elif col_name in ["Zone", "LhoName", "LHOName", "Circle"]:
            return "SBI Administrative Circle, LHO (Local Head Office) circle, or zone name"
        elif col_name in ["Operatorname", "AssignedOperator", "UserName"]:
            return "Name of SOC operator assigned to or handling the incident ticket workload"
        elif col_name in ["SOP_Text", "StandardOperatingProcedure", "Steps"]:
            return "Standard Operating Procedure guidelines and escalation steps"
        elif "ip" in col_lower or "host" in col_lower:
            return "Network IP address or hostname of camera or edge device"
        elif "status" in col_lower:
            return f"Operational status state of {table_name}"
        elif "count" in col_lower or "total" in col_lower:
            return f"Numeric metric count for {col_name}"
        elif col_name.endswith("Id") or col_name.endswith("ID"):
            return f"Identifier key linking to {col_name[:-2]}"
        
        # General fallback inference
        inferred = f"[Inferred] {col_name.replace('_', ' ')} field ({col_type})"
        self.inferred_column_descriptions[f"{table_name}.{col_name}"] = inferred
        return inferred

    def _introspect_foreign_keys(self, inspector, table_names):
        """Introspects explicit DB foreign keys and infers implicit key relationships."""
        fk_edges = []
        for table_name in table_names:
            try:
                fks = inspector.get_foreign_keys(table_name)
                for fk in fks:
                    target_table = fk.get('referred_table')
                    constrained_cols = fk.get('constrained_columns', [])
                    referred_cols = fk.get('referred_columns', [])
                    if target_table in table_names:
                        for c_col, r_col in zip(constrained_cols, referred_cols):
                            edge = {
                                "source_table": table_name,
                                "source_col": c_col,
                                "target_table": target_table,
                                "target_col": r_col
                            }
                            if edge not in fk_edges:
                                fk_edges.append(edge)
            except Exception:
                pass

        # Implicit foreign key relationship inference by key column names
        key_cols = ['incidentid', 'cameraid', 'locationid', 'branchid', 'alertid', 'zoneid', 'area']
        for i, t1 in enumerate(table_names):
            for t2 in table_names[i+1:]:
                if t1 not in self.tables_schema or t2 not in self.tables_schema:
                    continue
                cols1_map = {c['name'].lower(): c['name'] for c in self.tables_schema[t1]['columns']}
                cols2_map = {c['name'].lower(): c['name'] for c in self.tables_schema[t2]['columns']}
                
                common_keys = set(cols1_map.keys()).intersection(set(cols2_map.keys())).intersection(set(key_cols))
                for k_lower in common_keys:
                    col1_name = cols1_map[k_lower]
                    col2_name = cols2_map[k_lower]
                    edge = {
                        "source_table": t1,
                        "source_col": col1_name,
                        "target_table": t2,
                        "target_col": col2_name
                    }
                    if edge not in fk_edges:
                        fk_edges.append(edge)

        return fk_edges

    def _get_table_row_count(self, conn, table_name):
        """Helper to safely fetch row count of a table."""
        try:
            res = conn.execute(text(f"SELECT COUNT(*) FROM [{table_name}]")).scalar()
            return res or 0
        except Exception:
            return 0

    def _build_schema_vector_index(self):
        """
        Encodes table names, column names, and semantic contextual descriptions 
        into dense vector embeddings for semantic schema linking.
        """
        if not self.embedder or not self.tables_schema:
            return

        self.schema_vector_index = []
        texts_to_encode = []
        metadata_list = []

        for table_name, table_data in self.tables_schema.items():
            col_names_str = ", ".join([c["name"] for c in table_data["columns"][:10]])
            # Table-level semantic document enriched with domain terms
            domain_terms = ""
            if "alert" in table_name.lower():
                domain_terms = " security alerts, telemetry alarms, circles, response time delay, ack time, severity"
            elif "incident" in table_name.lower():
                domain_terms = " incidents, operator ticket workload, caller events, priorities, ticket status"
            elif "camera" in table_name.lower():
                domain_terms = " cctv camera devices, offline status, device locations"

            table_doc = f"Table {table_name}: stores records for {table_name.replace('_', ' ')}.{domain_terms} Columns: {col_names_str}"
            texts_to_encode.append(table_doc)
            metadata_list.append({
                "type": "table",
                "table_name": table_name,
                "column_name": None,
                "text": table_doc
            })

            # Column-level semantic documents with descriptions
            for col in table_data["columns"]:
                samples_str = f" (samples: {', '.join(col['sample_values'])})" if col['sample_values'] else ""
                desc_str = f" - {col['description']}" if col.get('description') else ""
                col_doc = f"Column {table_name}.{col['name']} ({col['type']}){desc_str}: stores {col['name'].replace('_', ' ')}{samples_str}"
                texts_to_encode.append(col_doc)
                metadata_list.append({
                    "type": "column",
                    "table_name": table_name,
                    "column_name": col['name'],
                    "text": col_doc
                })

        if texts_to_encode:
            embeddings = self.embedder.encode(texts_to_encode, convert_to_tensor=True, show_progress_bar=False)
            for meta, emb in zip(metadata_list, embeddings):
                meta["embedding"] = emb
                self.schema_vector_index.append(meta)

    def generate_dynamic_schema_prompt(self, dialect="Microsoft SQL Server"):
        """
        Generates a clean markdown string detailing the dynamic database schema & FK graph.
        """
        if not self.tables_schema:
            return "No schema available."

        lines = [f"Dynamic Database Schema Graph ({dialect}):\n"]
        idx = 1
        for table_name, table_info in self.tables_schema.items():
            lines.append(f"{idx}. Table '{table_name}' (total rows: {table_info.get('row_count', 0)}):")
            for col in table_info["columns"]:
                pk_str = " [PRIMARY KEY]" if col["primary_key"] else ""
                desc = f" - {col['description']}" if col.get('description') else ""
                samples = f" (sample values: {', '.join(col['sample_values'])})" if col['sample_values'] else ""
                lines.append(f"   - {col['name']} ({col['type']}){pk_str}{desc}{samples}")
            lines.append("")
            idx += 1

        if self.fk_edges:
            lines.append("Foreign Key Relationships (Graph Edges):")
            for edge in self.fk_edges:
                lines.append(f"   - {edge['source_table']}.{edge['source_col']} <-> {edge['target_table']}.{edge['target_col']}")
            lines.append("")

        return "\n".join(lines)

