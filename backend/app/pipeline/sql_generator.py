import re
import requests
from app.config import config

class SQLGenerator:
    """
    Stage 9: SQL Generation
    Converts validated JSON query plan + relevant schema subset into valid SQL query text.
    Calls local Ollama model (sqlcoder:15b or qwen2.5-coder) or uses deterministic SQL builder fallback.
    """
    def __init__(self):
        self.ollama_host = config.OLLAMA_HOST
        self.ollama_model = config.OLLAMA_MODEL

    def generate_sql(self, validated_plan: dict, schema_subset: dict, retry_error: str = None) -> str:
        """
        Generates SQL text.
        """
        prompt = self._build_prompt(validated_plan, schema_subset, retry_error)

        try:
            resp = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1}
                },
                timeout=config.OLLAMA_TIMEOUT
            )
            if resp.status_code == 200:
                raw_text = resp.json().get("response", "")
                sql = self._extract_sql(raw_text)
                if sql:
                    return sql, False
        except Exception as e:
            print(f"[SQL GENERATOR WARNING] Ollama call offline/failed ({e}). Using deterministic SQL synthesis.", flush=True)

        # Fallback Deterministic SQL Builder from JSON Plan
        sql = self._deterministic_sql_builder(validated_plan, schema_subset)
        return sql, True

    def _build_prompt(self, plan: dict, schema: dict, retry_error: str) -> str:
        prompt_parts = [
            "### System Prompt:\n",
            "Generate ONLY valid executable SQL query matching the query plan and database schema below. Do not wrap in markdown or commentary.\n\n",
            "CRITICAL DOMAIN RULES:\n",
            "1. In AlertsDetails table, column Area represents Monitored Branch / Administrative Office (e.g. AO_NOIDA, AO_AGRA, AO_NORTH AND WEST DELHI). For questions asking about 'branch' or 'branches' (or specific branches like Noida, Agra, Delhi), filter or group strictly on column Area.\n",
            "2. Column Zone represents SBI LHO Command Circle (e.g. NEW DELHI). Use Zone only when LHO/Circle is explicitly asked.\n",
            "3. For location text filters (Area or Zone), use LIKE '%<val>%' (e.g. Area LIKE '%NOIDA%') to match branch prefixes.\n\n",
            f"### Query Plan:\n{plan}\n\n",
            f"### Relevant Schema:\n{schema.get('tables', {})}\n\n"
        ]
        if schema.get("join_paths"):
            prompt_parts.append(f"### Join Relationships:\n{schema.get('join_paths')}\n\n")
        if retry_error:
            prompt_parts.append(f"### Previous Error to Fix:\n{retry_error}\n\n")

        prompt_parts.append("### SQL Query:\n")
        return "".join(prompt_parts)

    def _extract_sql(self, text: str) -> str:
        match = re.search(r'```sql\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Strip generic markdown backticks
        clean = text.replace("```", "").strip()
        lines = [line for line in clean.split("\n") if line.strip() and not line.strip().startswith("--")]
        return " ".join(lines)

    def _deterministic_sql_builder(self, plan: dict, schema_subset: dict = None) -> str:
        intent = plan.get("intent", "SELECT").upper()
        tables = plan.get("tables_needed", ["Incident_Data"])
        primary_table = tables[0]

        # Get available column names for primary table from schema_subset if present
        table_cols = []
        if schema_subset and "tables" in schema_subset and primary_table in schema_subset["tables"]:
            cols_info = schema_subset["tables"][primary_table]
            table_cols = [c["name"] if isinstance(c, dict) else str(c) for c in cols_info]

        group_by = plan.get("group_by")
        select_cols = plan.get("select_columns")
        limit = plan.get("limit")
        select_clause = "*"

        if intent in ["SUMMARY", "GROUP_BY"] or group_by:
            if group_by:
                gb_select = [f"RTRIM(LTRIM({primary_table}.[{g}])) AS [{g}]" for g in group_by]
                select_clause = f"{', '.join(gb_select)}, COUNT(*) AS TotalAlerts"
            else:
                select_clause = f"COUNT(*) AS TotalAlerts"
        elif intent == "COUNT":
            select_clause = "COUNT(*) AS TotalAlerts"
        elif intent in ["AVG", "SUM", "MAX", "MIN"]:
            target_col = None
            for c in table_cols:
                clow = c.lower()
                if any(k in clow for k in ["time", "duration", "latency", "count", "rate", "sla", "id"]):
                    target_col = c
                    break
            if not target_col and table_cols:
                target_col = table_cols[0]
            
            col_expr = f"{primary_table}.[{target_col}]" if target_col else "1"
            select_clause = f"{intent}({col_expr})"
        elif select_cols:
            valid_qualified = []
            for sc in select_cols:
                matched_name = next((tc for tc in table_cols if tc.lower() == sc.lower()), sc)
                valid_qualified.append(f"{primary_table}.[{matched_name}]")
            select_clause = ", ".join(valid_qualified)

        distinct = plan.get("distinct") or intent == "SELECT_DISTINCT"
        order_by = plan.get("order_by")

        distinct_clause = "DISTINCT " if distinct else ""
        top_clause = f"TOP {limit} " if limit else ""

        if distinct:
            if select_cols:
                valid_sel = []
                for sc in select_cols:
                    matched_name = next((tc for tc in table_cols if tc.lower() == sc.lower()), sc)
                    valid_sel.append(f"RTRIM(LTRIM({primary_table}.[{matched_name}])) AS [{matched_name}]")
                select_clause = ", ".join(valid_sel)
            else:
                select_clause = f"RTRIM(LTRIM({primary_table}.[Zone])) AS [Zone]"

        sql = f"SELECT {distinct_clause}{top_clause}{select_clause} FROM {primary_table}"

        # Multi-table join handling: find common column or FK relationship
        if len(tables) > 1 and schema_subset:
            sec_table = tables[1]
            sec_cols = []
            if "tables" in schema_subset and sec_table in schema_subset["tables"]:
                sec_cols = [c["name"] if isinstance(c, dict) else str(c) for c in schema_subset["tables"][sec_table]]
            
            # Find matching FK column name between tables
            ignored_join_keys = ["systemname", "status", "area", "zone", "location", "createdby", "updatedby", "id", "guid"]
            common = [c for c in table_cols if c in sec_cols and c.lower() not in ignored_join_keys]
            if common:
                join_col = common[0]
                sql += f" JOIN {sec_table} ON {primary_table}.[{join_col}] = {sec_table}.[{join_col}]"

        # Build WHERE clause components from plan filters
        where_parts = []
        raw_filters = plan.get("filters", [])
        if isinstance(raw_filters, dict):
            for col, val in raw_filters.items():
                if val is not None and str(val).strip() != "":
                    if isinstance(val, (int, float)) or str(val).isdigit():
                        where_parts.append(f"{primary_table}.[{col}] = {val}")
                    else:
                        safe_val = str(val).replace("'", "''")
                        where_parts.append(f"{primary_table}.[{col}] = '{safe_val}'")
        elif isinstance(raw_filters, list):
            for f in raw_filters:
                if not isinstance(f, dict):
                    continue
                col = f.get("column")
                op = f.get("operator", "=")
                val = f.get("value")
                is_date_cast = f.get("is_date_cast", False)
                tbl = primary_table # Force primary_table unless multi-table join is present

                if col and val is not None and str(val).strip() != "":
                    # Remap Location to Area if value is a known branch name (e.g., AO_NOIDA, Noida)
                    if col == "Location" and any(b in str(val).upper() for b in ["NOIDA", "AGRA", "DELHI", "AO_"]):
                        col = "Area"

                    col_ref = f"{tbl}.[{col}]"
                    if is_date_cast:
                        if op == "=":
                            where_parts.append(f"CAST({col_ref} AS DATE) = '{val}'")
                        else:
                            where_parts.append(f"CAST({col_ref} AS DATE) {op} '{val}'")
                    elif isinstance(val, (int, float)) or (isinstance(val, str) and val.isdigit()):
                        where_parts.append(f"{col_ref} {op} {val}")
                    else:
                        safe_val = str(val).replace("'", "''")
                        if col in ["Area", "Zone", "Location"] and op == "=":
                            # Clean up prefix for LIKE query (e.g. AO_NOIDA -> NOIDA)
                            clean_like = safe_val.replace("AO_", "").strip()
                            where_parts.append(f"{col_ref} LIKE '%{clean_like}%'")
                        else:
                            where_parts.append(f"{col_ref} {op} '{safe_val}'")

        if where_parts:
            sql += " WHERE " + " AND ".join(where_parts)

        if group_by:
            gb_exprs = [f"RTRIM(LTRIM({primary_table}.[{g}]))" for g in group_by]
            sql += f" GROUP BY {', '.join(gb_exprs)}"

        if order_by:
            if "TotalAlerts" in order_by or "COUNT" in order_by:
                sql += f" ORDER BY {order_by}"
            else:
                order_col = order_by.split()[0]
                order_dir = order_by.split()[1] if len(order_by.split()) > 1 else "DESC"
                sql += f" ORDER BY {primary_table}.[{order_col}] {order_dir}"

        return sql
