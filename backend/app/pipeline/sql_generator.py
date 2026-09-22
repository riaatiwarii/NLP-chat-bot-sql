import re
import requests
from app.config import config
from app.pipeline.sql_ident import (
    bracket,
    qualify,
    resolve_allowed_column,
    resolve_allowed_table,
    resolve_limit,
    resolve_operator,
    resolve_order_dir,
)

class SQLGenerator:
    """
    Stage 9: SQL Generation

    Executable SQL is always built from the validated JSON plan with:
    - bound parameters for every filter value
    - table/column names resolved against ALLOWED_TABLES + introspected columns

    Ollama may propose SQL for unseen phrasings; that text is never executed.
    """
    def __init__(self):
        self.ollama_host = config.OLLAMA_HOST
        self.ollama_model = config.OLLAMA_MODEL

    def generate_sql(self, validated_plan: dict, schema_subset: dict, retry_error: str = None) -> tuple[str, dict, bool]:
        if getattr(config, 'USE_LLM_SQL_DRAFT', False):
            try:
                resp = requests.post(
                    f"{self.ollama_host}/api/generate",
                    json={
                        "model": self.ollama_model,
                        "prompt": self._build_prompt(validated_plan, schema_subset, retry_error),
                        "stream": False,
                        "options": {"temperature": 0.1}
                    },
                    timeout=config.OLLAMA_TIMEOUT
                )
                if resp.status_code == 200:
                    draft = self._extract_sql(resp.json().get("response", ""))
                    if draft:
                        print(f"[SQL GENERATOR] LLM SQL draft ignored for execution (not parameterized):\n{draft}", flush=True)
            except Exception as e:
                print(f"[SQL GENERATOR INFO] Ollama SQL draft skipped ({e}).", flush=True)

        sql, params = self._deterministic_sql_builder(validated_plan, schema_subset)
        print(f"[SQL GENERATOR] Generated SQL: {sql}")
        print(f"[SQL GENERATOR] Generated params: {params}")
        return sql, params, True

    def _build_prompt(self, plan: dict, schema: dict, retry_error: str) -> str:
        prompt_parts = [
            "### System Prompt:\n",
            "Generate ONLY valid executable SQL query matching the query plan and database schema below. Do not wrap in markdown or commentary.\n\n",
            "CRITICAL DOMAIN RULES:\n",
            "1. Primary alert table is vw_AlertReporting (Branch, LHOCircle) or AlertsDetails (Area, Zone).\n",
            "2. For location text filters, use LIKE with a bound parameter (never concatenate user text).\n",
            "3. For GROUP BY summaries always include COUNT(*) AS TotalAlerts.\n\n",
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
        clean = text.replace("```", "").strip()
        lines = [line for line in clean.split("\n") if line.strip() and not line.strip().startswith("--")]
        return " ".join(lines)

    def _table_columns(self, table: str, schema_subset: dict) -> list[str]:
        tables = (schema_subset or {}).get("tables", {})
        cols_info = tables.get(table, [])
        return [c["name"] if isinstance(c, dict) else str(c) for c in cols_info]

    def _bind(self, params: dict, value) -> str:
        name = f"p{len(params)}"
        params[name] = value
        return f":{name}"

    def _deterministic_sql_builder(self, plan: dict, schema_subset: dict = None) -> tuple[str, dict]:
        intent = (plan.get("intent") or "SELECT").upper()
        raw_tables = plan.get("tables_needed") or ["vw_AlertReporting"]
        tables = [resolve_allowed_table(t) for t in raw_tables]
        primary_table = tables[0]
        table_cols = self._table_columns(primary_table, schema_subset)
        if not table_cols:
            table_cols = list(config.DEFAULT_DISPLAY_COLUMNS)

        params: dict = {}
        group_by = plan.get("group_by") or []
        select_cols = plan.get("select_columns") or []
        limit = resolve_limit(plan.get("limit"))
        group_by_is_date = bool(plan.get("group_by_is_date"))

        def gb_expr(col: str) -> str:
            expr = qualify(primary_table, col)
            return f"CAST({expr} AS DATE)" if group_by_is_date else f"RTRIM(LTRIM({expr}))"

        if intent == "COUNT_DISTINCT" or plan.get("aggregation") == "COUNT_DISTINCT":
            # "how many <dimension>" = distinct value count of that column, never total row count.
            dim_col = resolve_allowed_column(select_cols[0] if select_cols else table_cols[0], table_cols)
            dim_expr = f"CAST({qualify(primary_table, dim_col)} AS DATE)" if group_by_is_date else qualify(primary_table, dim_col)
            select_clause = f"COUNT(DISTINCT {dim_expr}) AS TotalAlerts"
            limit = None
            group_by = []
        elif intent in ["SUMMARY", "GROUP_BY"] or group_by:
            if group_by:
                resolved_gb = [resolve_allowed_column(g, table_cols) for g in group_by]
                gb_select = [f"{gb_expr(g)} AS {bracket(g)}" for g in resolved_gb]
                select_clause = f"{', '.join(gb_select)}, COUNT(*) AS TotalAlerts"
                group_by = resolved_gb
            else:
                select_clause = "COUNT(*) AS TotalAlerts"
                limit = None  # COUNT queries should not have LIMIT
        elif intent == "COUNT":
            select_clause = "COUNT(*) AS TotalAlerts"
            limit = None  # COUNT queries should not have LIMIT
        elif intent in ["AVG", "SUM", "MAX", "MIN"]:
            target_col = None
            for c in table_cols:
                clow = c.lower()
                if any(k in clow for k in ["time", "duration", "latency", "count", "rate", "sla", "id"]):
                    target_col = resolve_allowed_column(c, table_cols)
                    break
            if not target_col and table_cols:
                target_col = resolve_allowed_column(table_cols[0], table_cols)
            col_expr = qualify(primary_table, target_col) if target_col else "1"
            select_clause = f"{intent}({col_expr})"
        elif select_cols:
            valid_qualified = []
            for sc in select_cols:
                if str(sc).lower() in ["totalalerts", "count(*)", "count"]:
                    valid_qualified.append("COUNT(*) AS TotalAlerts")
                else:
                    matched_name = resolve_allowed_column(sc, table_cols)
                    valid_qualified.append(qualify(primary_table, matched_name))
            select_clause = ", ".join(valid_qualified)
        else:
            select_clause = "*"

        distinct = plan.get("distinct") or intent == "SELECT_DISTINCT"
        order_by = plan.get("order_by")
        distinct_clause = "DISTINCT " if distinct else ""
        top_clause = f"TOP {limit} " if limit else ""

        where_parts = []
        if distinct:
            sel_col_name = resolve_allowed_column(select_cols[0] if select_cols else table_cols[0], table_cols)
            select_clause = f"RTRIM(LTRIM({qualify(primary_table, sel_col_name)})) AS {bracket(sel_col_name)}"
            empty_ph = self._bind(params, "")
            where_parts.append(
                f"{qualify(primary_table, sel_col_name)} IS NOT NULL AND RTRIM(LTRIM({qualify(primary_table, sel_col_name)})) != {empty_ph}"
            )

        sql = f"SELECT {distinct_clause}{top_clause}{select_clause} FROM {primary_table}"

        if len(tables) > 1 and schema_subset:
            sec_table = tables[1]
            sec_cols = self._table_columns(sec_table, schema_subset)
            ignored_join_keys = ["systemname", "status", "area", "zone", "location", "createdby", "updatedby", "id", "guid"]
            common = [c for c in table_cols if c in sec_cols and c.lower() not in ignored_join_keys]
            if common:
                join_col = resolve_allowed_column(common[0], table_cols)
                join_col_sec = resolve_allowed_column(join_col, sec_cols)
                sql += f" JOIN {sec_table} ON {qualify(primary_table, join_col)} = {qualify(sec_table, join_col_sec)}"

        raw_filters = plan.get("filters", [])
        if isinstance(raw_filters, dict):
            raw_filters = [{"column": k, "operator": "=", "value": v} for k, v in raw_filters.items()]

        # Deduplicate filters by column to prevent impossible conditions
        seen_columns = set()
        deduped_filters = []
        for f in raw_filters or []:
            col = f.get("column")
            if col and col.lower() not in seen_columns:
                seen_columns.add(col.lower())
                deduped_filters.append(f)
        
        for f in deduped_filters:
            if not isinstance(f, dict):
                continue
            col = f.get("column")
            op = f.get("operator", "=")
            val = f.get("value")
            is_date_cast = f.get("is_date_cast", False)
            if col is None or val is None or str(val).strip() == "":
                continue

            if primary_table == "vw_AlertReporting":
                if col.lower() in ["area", "location"]:
                    col = "Branch"
                elif col.lower() in ["zone", "lho"]:
                    col = "LHOCircle"
            elif col == "Location" and any(b in str(val).upper() for b in ["NOIDA", "AGRA", "DELHI", "AO_"]):
                col = "Area"

            col = resolve_allowed_column(col, table_cols)
            col_ref = qualify(primary_table, col)

            if is_date_cast:
                from datetime import datetime, timedelta
                val_clean = str(f.get("start_date") or val).strip()
                end_clean = str(f.get("end_date") or "").strip()
                try:
                    dt_obj = datetime.strptime(val_clean[:10], "%Y-%m-%d")
                    start_str = dt_obj.strftime("%Y-%m-%d 00:00:00")
                except Exception:
                    start_str = f"{val_clean} 00:00:00"

                if end_clean:
                    try:
                        dt_end_obj = datetime.strptime(end_clean[:10], "%Y-%m-%d")
                        end_str = dt_end_obj.strftime("%Y-%m-%d 00:00:00")
                    except Exception:
                        end_str = f"{end_clean} 00:00:00"
                else:
                    try:
                        next_dt = dt_obj + timedelta(days=1)
                        end_str = next_dt.strftime("%Y-%m-%d 00:00:00")
                    except Exception:
                        end_str = f"{val_clean} 23:59:59"

                ph_start = self._bind(params, start_str)
                ph_end = self._bind(params, end_str)

                # Check both Datetime and AlertOccuranceTime columns if available
                has_occur_col = any(c.lower() in ["alertoccurancetime", "alertoccurance_time", "occurancetime"] for c in table_cols)
                if col.lower() in ["datetime", "createdtime"] and has_occur_col:
                    occur_col = next(c for c in table_cols if c.lower() in ["alertoccurancetime", "alertoccurance_time", "occurancetime"])
                    col_alt = qualify(primary_table, occur_col)
                    where_parts.append(f"(({col_ref} >= {ph_start} AND {col_ref} < {ph_end}) OR ({col_alt} >= {ph_start} AND {col_alt} < {ph_end}))")
                else:
                    where_parts.append(f"({col_ref} >= {ph_start} AND {col_ref} < {ph_end})")
            elif col in ["Area", "Branch", "Zone", "LHOCircle", "Location"] and op == "=":
                clean_like = str(val).replace("AO_", "").strip().upper()
                ph = self._bind(params, f"%{clean_like}%")
                where_parts.append(f"{col_ref} LIKE {ph}")
            else:
                op_clean = resolve_operator(op)
                bind_val = int(val) if isinstance(val, str) and val.isdigit() else val
                ph = self._bind(params, bind_val)
                where_parts.append(f"{col_ref} {op_clean} {ph}")

        # Ensure dimension columns are NOT NULL for ranking queries (e.g. "Which branch has the highest")
        if group_by and limit == 1:
            for g in group_by:
                not_null_expr = f"{qualify(primary_table, g)} IS NOT NULL"
                if not_null_expr not in where_parts:
                    where_parts.append(not_null_expr)

        if intent == "COUNT_DISTINCT" or plan.get("aggregation") == "COUNT_DISTINCT":
            dim_col_ref = qualify(primary_table, resolve_allowed_column(select_cols[0] if select_cols else table_cols[0], table_cols))
            not_null_expr = f"{dim_col_ref} IS NOT NULL"
            if not_null_expr not in where_parts:
                where_parts.append(not_null_expr)

        if where_parts:
            sql += " WHERE " + " AND ".join(where_parts)

        if group_by:
            gb_exprs = [gb_expr(g) for g in group_by]
            sql += f" GROUP BY {', '.join(gb_exprs)}"

        if order_by:
            if "TotalAlerts" in str(order_by) or "COUNT" in str(order_by).upper():
                direction = "DESC"
                parts = str(order_by).split()
                if len(parts) > 1:
                    direction = resolve_order_dir(parts[-1])
                sql += f" ORDER BY TotalAlerts {direction}"
            else:
                parts = str(order_by).split()
                order_col = resolve_allowed_column(parts[0], table_cols)
                order_dir = resolve_order_dir(parts[1] if len(parts) > 1 else "DESC")
                sql += f" ORDER BY {qualify(primary_table, order_col)} {order_dir}"
        elif intent in ["SUMMARY", "GROUP_BY"] and group_by:
            # Default ORDER BY for summary/group by queries to get highest counts
            sql += " ORDER BY TotalAlerts DESC"

        return sql, params
