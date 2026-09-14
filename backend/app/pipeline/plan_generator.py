import json
import requests
from datetime import datetime, timedelta
from app.config import config

class PlanGenerator:
    """
    Stage 7: Structured Query Plan Generation
    Calls local LLM via Ollama (or uses deterministic plan builder fallback) to generate a strict JSON query plan.
    Supports plan diffing when handling follow-up turns.
    """
    def __init__(self):
        self.ollama_host = config.OLLAMA_HOST
        self.ollama_model = config.OLLAMA_RESPONSE_MODEL

    def generate_plan(
        self,
        normalized_query: str,
        resolved_entities: list[dict],
        resolved_intent: str,
        schema_subset: dict,
        prior_plan: dict = None,
        is_followup: bool = False,
        validation_error: str = None
    ) -> dict:
        """
        Generates strict JSON query plan.
        """
        prompt = self._build_prompt(
            normalized_query, resolved_entities, resolved_intent, schema_subset, prior_plan, is_followup, validation_error
        )

        try:
            resp = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                },
                timeout=config.OLLAMA_TIMEOUT
            )
            if resp.status_code == 200:
                raw_json = resp.json().get("response", "")
                parsed = json.loads(raw_json)
                if isinstance(parsed, dict) and "tables_needed" in parsed:
                    return parsed
        except Exception as e:
            print(f"[PLAN GENERATOR WARNING] Ollama call offline/failed ({e}). Using deterministic plan builder.", flush=True)

        # Fallback Deterministic Plan Builder
        return self._deterministic_plan_builder(
            normalized_query, resolved_entities, resolved_intent, schema_subset, prior_plan, is_followup
        )

    def _build_prompt(
        self, query: str, entities: list, intent: str, schema: dict, prior_plan: dict, is_followup: bool, err: str
    ) -> str:
        prompt_parts = [
            "You are a database query plan planner. Output ONLY strict JSON according to this schema:\n",
            "{\n  \"intent\": \"SELECT|SUMMARY|COUNT|AVG|SUM|MAX|MIN\",\n  \"tables_needed\": [\"table_name\"],\n  \"select_columns\": [\"col_name\"],\n  \"filters\": [{\"table\": \"table_name\", \"column\": \"col_name\", \"operator\": \"=\", \"value\": \"val\"}],\n  \"group_by\": [\"col_name\"] or null,\n  \"aggregation\": \"COUNT|AVG|SUM|MAX|MIN\" or null,\n  \"limit\": 50 or null\n}\n\n",
            f"User Query: {query}\n",
            f"Resolved Intent: {intent}\n",
            f"Resolved Entities: {json.dumps(entities)}\n",
            f"Relevant Schema: {json.dumps(schema.get('tables', {}))}\n"
        ]
        if is_followup and prior_plan:
            prompt_parts.append(f"Prior Plan to update/diff against: {json.dumps(prior_plan)}\n")
        if err:
            prompt_parts.append(f"Validation Error from previous attempt: {err}\n")

        prompt_parts.append("\nJSON Output:")
        return "".join(prompt_parts)

    def _deterministic_plan_builder(
        self, query: str, entities: list, intent: str, schema: dict, prior_plan: dict, is_followup: bool
    ) -> dict:
        tables = list(schema.get("tables", {}).keys())
        query_lower = query.lower()

        # Prioritize primary alert/telemetry tables for dashboard/summary/detail queries
        primary_table = None
        if any(w in query_lower for w in ["summary", "dashboard", "alert", "telemetry"]):
            for pref in ["AlertsDetails", "Alerts", "Incident_Data", "AlertHistory"]:
                if pref in tables:
                    primary_table = pref
                    break

        if not primary_table:
            primary_table = tables[0] if tables else "AlertsDetails"

        table_cols_info = schema.get("tables", {}).get(primary_table, [])
        table_cols = [c["name"] if isinstance(c, dict) else str(c) for c in table_cols_info]

        # Compute display columns for primary table (exclude internal columns and raw coordinates)
        internal_set = {ic.lower() for ic in config.INTERNAL_COLUMNS}
        select_columns = [c for c in table_cols if c.lower() not in internal_set]
        if not select_columns:
            select_columns = [c for c in table_cols if c in config.DEFAULT_DISPLAY_COLUMNS] or table_cols[:5]

        filters = []
        filtered_cols = set()
        for e in entities:
            if e.get("type") in ["date_relative", "date_explicit"]:
                continue
            if e.get("is_resolved") and e.get("matched_column"):
                col = e["matched_column"]
                # Verify col exists in primary_table, otherwise find table containing col
                if col.lower() not in [c.lower() for c in table_cols]:
                    for alt_tbl in tables:
                        alt_cols = [c["name"].lower() if isinstance(c, dict) else str(c).lower() for c in schema.get("tables", {}).get(alt_tbl, [])]
                        if col.lower() in alt_cols:
                            primary_table = alt_tbl
                            table_cols_info = schema.get("tables", {}).get(primary_table, [])
                            table_cols = [c["name"] if isinstance(c, dict) else str(c) for c in table_cols_info]
                            select_columns = [c for c in table_cols if c.lower() not in internal_set]
                            break

                filters.append({
                    "table": primary_table,
                    "column": col,
                    "operator": "=",
                    "value": e["resolved_value"]
                })
                filtered_cols.add(col.lower())

        # Timezone-aware Date Filter Resolution
        date_col = None
        for c in table_cols:
            if c.lower() in ["createdtime", "datetime", "timestamp", "createddate", "alertcreateime", "time"]:
                date_col = c
                break

        if date_col and not any(f["column"].lower() == date_col.lower() for f in filters):
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(config.TIMEZONE)
            except Exception:
                tz = None

            now = datetime.now(tz) if tz else datetime.now()

            if "today" in query_lower:
                filters.append({
                    "table": primary_table,
                    "column": date_col,
                    "operator": "=",
                    "value": now.strftime("%Y-%m-%d"),
                    "is_date_cast": True
                })
            elif "yesterday" in query_lower:
                yesterday = now - timedelta(days=1)
                filters.append({
                    "table": primary_table,
                    "column": date_col,
                    "operator": "=",
                    "value": yesterday.strftime("%Y-%m-%d"),
                    "is_date_cast": True
                })
            elif any(w in query_lower for w in ["this week", "last 7 days"]):
                start_week = now - timedelta(days=7)
                filters.append({
                    "table": primary_table,
                    "column": date_col,
                    "operator": ">=",
                    "value": start_week.strftime("%Y-%m-%d"),
                    "is_date_cast": True
                })

        # Context-Sensitive Group-By & Ranking Selection
        group_by = None
        aggregation = intent if intent not in ["SELECT", "SUMMARY", "SELECT_DISTINCT"] else None
        limit = config.LIST_QUERY_ROW_LIMIT if intent in ["SELECT", "SELECT_DISTINCT"] else None
        order_by = None
        distinct = False

        if intent == "SELECT_DISTINCT" or any(k in query_lower for k in ["list the lhos", "list lhos", "list branches", "list zones"]):
            intent = "SELECT_DISTINCT"
            distinct = True
            limit = None
            for c in table_cols:
                if c.lower() in ["zone", "area", "location", "branch"]:
                    select_columns = [c]
                    break

        elif any(k in query_lower for k in ["highest", "most", "top", "max"]):
            intent = "SUMMARY"
            aggregation = "COUNT"
            order_by = "TotalAlerts DESC"
            limit = 1 if "which" in query_lower or "highest" in query_lower or "top 1" in query_lower else 5
            for c in table_cols:
                if c.lower() in ["zone", "area", "location", "branch"]:
                    group_by = [c]
                    break
            if not group_by:
                group_by = [table_cols[0]]

        elif intent in ["SUMMARY", "GROUP_BY"] or any(k in query_lower for k in ["summary", "dashboard", "breakdown"]):
            intent = "SUMMARY"
            aggregation = "COUNT"
            limit = None # Aggregated summaries stay uncapped

            if "status" in query_lower and "status" not in filtered_cols:
                status_cols = [c for c in table_cols if c.lower() == "status"]
                if status_cols:
                    group_by = status_cols
            elif "severity" in query_lower and "severity" not in filtered_cols:
                sev_cols = [c for c in table_cols if c.lower() == "severity"]
                if sev_cols:
                    group_by = sev_cols
            elif any(k in query_lower for k in ["location", "branch", "area", "zone"]):
                loc_cols = [c for c in table_cols if c.lower() in ["location", "zone", "area", "branch"]]
                if loc_cols and loc_cols[0].lower() not in filtered_cols:
                    group_by = [loc_cols[0]]

            if not group_by:
                candidate_dims = []
                for dim_keyword in ["location", "zone", "area", "status", "severity", "alerttype"]:
                    for c in table_cols:
                        if c.lower() == dim_keyword and c.lower() not in filtered_cols and c not in candidate_dims:
                            candidate_dims.append(c)
                            break
                group_by = candidate_dims[:3] if candidate_dims else None

        if intent == "SUMMARY" and group_by:
            select_columns = list(group_by) + ["TotalAlerts"]

        if any(k in query_lower for k in ["recent", "latest", "newest"]):
            order_by = "Datetime DESC" if "datetime" in [c.lower() for c in table_cols] else "CreatedTime DESC"

        # Follow-up diffing: update filters from prior turn
        if is_followup and prior_plan:
            base_plan = dict(prior_plan)
            base_plan["intent"] = intent if intent != "SELECT" else base_plan.get("intent", "SELECT")
            base_plan["select_columns"] = select_columns
            base_plan["limit"] = limit
            base_plan["order_by"] = order_by
            base_plan["distinct"] = distinct
            if filters:
                existing_cols = {f["column"]: i for i, f in enumerate(base_plan.get("filters", []))}
                for new_f in filters:
                    if new_f["column"] in existing_cols:
                        base_plan["filters"][existing_cols[new_f["column"]]] = new_f
                    else:
                        base_plan.setdefault("filters", []).append(new_f)
            return base_plan

        return {
            "intent": intent,
            "tables_needed": [primary_table],
            "select_columns": select_columns,
            "filters": filters,
            "group_by": group_by,
            "aggregation": aggregation,
            "limit": limit,
            "order_by": order_by,
            "distinct": distinct
        }
