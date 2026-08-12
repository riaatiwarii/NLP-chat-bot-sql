import os
import json
import numpy as np
from sqlalchemy import inspect, text
from sentence_transformers import SentenceTransformer, util

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

        self._load_embedder()
        if self.engine is not None:
            self.introspect_database()

    def _load_embedder(self):
        """Loads sentence-transformers model for dense semantic embeddings."""
        try:
            print(f"[SCHEMA ENGINE] Loading semantic embedding model: '{self.model_name}'...")
            self.embedder = SentenceTransformer(self.model_name)
            print("[SCHEMA ENGINE] Semantic embedder loaded successfully.")
        except Exception as e:
            print(f"[SCHEMA ENGINE WARNING] Failed to load SentenceTransformer: {e}")
            self.embedder = None

    def introspect_database(self, engine=None):
        """
        Dynamically inspects tables, columns, data types, primary keys, 
        and distinct text sample values from the database engine.
        """
        if engine:
            self.engine = engine
        if not self.engine:
            print("[SCHEMA ENGINE WARNING] No database engine provided for introspection.")
            return {}

        print("[SCHEMA ENGINE] Introspecting database schema...")
        inspector = inspect(self.engine)
        schema_info = {}
        column_values = {}

        try:
            raw_table_names = inspector.get_table_names()
            # Filter out system, migration, and framework metadata tables
            excluded_prefixes = ('__', 'sys', 'dtproperties', 'AspNet', 'Log4', 'API_', 'DMS_', 'Token', 'AccessToken')
            table_names = [t for t in raw_table_names if not any(t.startswith(p) for p in excluded_prefixes)]
            
            # Prioritize core operational monitoring tables first
            priority_tables = ['CameraList', 'Incident_Data', 'AlertsDetails', 'Master_CamDetails', 'Location_Master', 'SOP_MASTER', 'IncidentHistory']
            ordered_tables = [t for t in priority_tables if t in table_names] + [t for t in table_names if t not in priority_tables]
            table_names = ordered_tables[:30]  # Cap to top 30 tables for lightning-fast vector indexing
        except Exception as e:
            print(f"[SCHEMA ENGINE ERROR] Could not fetch table names: {e}")
            return {}

        is_small_schema = len(table_names) <= 30

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
                        "sample_values": distinct_samples[:5]
                    })

                schema_info[table_name] = {
                    "columns": col_list,
                    "row_count": self._get_table_row_count(conn, table_name) if is_priority else 0
                }


        self.tables_schema = schema_info
        self.column_values_cache = column_values

        # Build dynamic vector embeddings for the introspected schema
        self._build_schema_vector_index()

        print(f"[SCHEMA ENGINE] Introspection complete. Discovered {len(schema_info)} tables across database.")
        return schema_info

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
            # Table-level semantic document
            table_doc = f"Table {table_name}: stores records for {table_name.replace('_', ' ').replace('List', ' List')}"
            texts_to_encode.append(table_doc)
            metadata_list.append({
                "type": "table",
                "table_name": table_name,
                "column_name": None,
                "text": table_doc
            })

            # Column-level semantic documents
            for col in table_data["columns"]:
                samples_str = f" (samples: {', '.join(col['sample_values'])})" if col['sample_values'] else ""
                col_doc = f"Column {table_name}.{col['name']} ({col['type']}): stores {col['name'].replace('_', ' ')}{samples_str}"
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
        Generates a clean markdown string detailing the dynamic database schema 
        to be injected into the LLM system prompt.
        """
        if not self.tables_schema:
            return "No schema available."

        lines = [f"Dynamic Database Schema ({dialect}):\n"]
        idx = 1
        for table_name, table_info in self.tables_schema.items():
            lines.append(f"{idx}. Table '{table_name}' (total rows: {table_info.get('row_count', 0)}):")
            for col in table_info["columns"]:
                pk_str = " [PRIMARY KEY]" if col["primary_key"] else ""
                samples = f" (sample values: {', '.join(col['sample_values'])})" if col['sample_values'] else ""
                lines.append(f"   - {col['name']} ({col['type']}){pk_str}{samples}")
            lines.append("")
            idx += 1

        return "\n".join(lines)
