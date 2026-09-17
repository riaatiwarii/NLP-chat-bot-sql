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
                    # Enforce ALLOWED_TABLES on LLM plan output
                    parsed["tables_needed"] = [t for t in parsed.get("tables_needed", []) if t in config.ALLOWED_TABLES] or ["AlertsDetails"]
                    # General Rule for SUMMARY Intent:
                    # Unless an explicit multi-category breakdown (by branch/severity/type) is requested, SUMMARY intent defaults group_by = ["Status"]
                    if parsed.get("intent") == "SUMMARY":
                        q_low = normalized_query.lower()
                        is_explicit_other_grouping = any(w in q_low for w in [
                            "by branch", "by location", "by area", "by zone", "grouped by branch", "breakdown by branch",
                            "breakdown by area", "breakdown by zone", "highest branch", "top branch", "which branch",
                            "breakdown by severity", "breakdown by type", "highest number of alerts"
                        ])
                        if not is_explicit_other_grouping:
                            parsed["group_by"] = ["Status"]
                            parsed["select_columns"] = ["Status", "TotalAlerts"]

                    # Ensure an aggregation column (TotalAlerts / Count) is present in select_columns for group_by plans
                    if parsed.get("group_by") and isinstance(parsed.get("select_columns"), list):
                        has_count_col = any(any(k in str(c).lower() for k in ["total", "count", "sum", "avg", "max", "min"]) for c in parsed["select_columns"])
                        if not has_count_col:
                            parsed["select_columns"].append("TotalAlerts")
                    return parsed, False
        except Exception as e:
            print(f"[PLAN GENERATOR WARNING] Ollama call offline/failed ({e}). Using deterministic plan builder.", flush=True)

        # Fallback Deterministic Plan Builder
        plan = self._deterministic_plan_builder(
            normalized_query, resolved_entities, resolved_intent, schema_subset, prior_plan, is_followup
        )
        return plan, True

    def _build_prompt(
        self, query: str, entities: list, intent: str, schema: dict, prior_plan: dict, is_followup: bool, err: str
    ) -> str:
        prompt_parts = [
            "You are a database query plan planner. Output ONLY strict JSON according to this schema:\n",
            "{\n  \"intent\": \"SELECT|SUMMARY|COUNT|AVG|SUM|MAX|MIN\",\n  \"tables_needed\": [\"table_name\"],\n  \"select_columns\": [\"col_name\"],\n  \"filters\": [{\"table\": \"table_name\", \"column\": \"col_name\", \"operator\": \"=\", \"value\": \"val\"}],\n  \"group_by\": [\"col_name\"] or null,\n  \"aggregation\": \"COUNT|AVG|SUM|MAX|MIN\" or null,\n  \"limit\": 50 or null\n}\n\n",
            "CRITICAL DOMAIN RULES:\n",
            "1. In AlertsDetails table, column Area represents Monitored Branch / Administrative Office (e.g. AO_NOIDA, AO_AGRA, AO_NORTH AND WEST DELHI). For questions asking about 'branch' or 'branches' (or specific branches like Noida, Agra, Delhi), set group_by or filters strictly on column Area.\n",
            "2. Column Zone represents SBI LHO Command Circle (e.g. NEW DELHI). Use Zone only when LHO, Circle, or Zone is explicitly asked.\n\n",
            f"User Query: {query}\n",
            f"Resolved Intent: {intent}\n",
            f"Resolved Entities: {json.dumps(entities)}\n",
            f"Relevant Schema (Allowed tables ONLY): {json.dumps({k: v for k, v in schema.get('tables', {}).items() if k in config.ALLOWED_TABLES})}\n"
        ]
        if is_followup and prior_plan:
            prompt_parts.append(f"Prior Plan to update/diff against: {json.dumps(prior_plan)}\n")
        if err:
            prompt_parts.append(f"Validation Error from previous attempt: {err}\n")

        prompt_parts.append("\nJSON Output:")
        return "".join(prompt_parts)

    def _find_best_table_for_columns(self, required_cols: list[str], schema: dict) -> str:
        """
        Dynamic Schema-Driven Table Routing Rule:
        Scores live introspected tables against required column capabilities.
        Routes to whichever table actually possesses the required columns in the live DB schema.
        """
        allowed_set = set(config.ALLOWED_TABLES)
        tables_dict = schema.get("tables", {})
        
        req_lowers = [rc.lower() for rc in required_cols]
        best_table = None
        max_score = -1
        
        for t_name, cols_info in tables_dict.items():
            if t_name not in allowed_set:
                continue
            col_names = [c["name"].lower() if isinstance(c, dict) else str(c).lower() for c in cols_info]
            score = sum(1 for rc in req_lowers if rc in col_names)
            
            if score > max_score:
                max_score = score
                best_table = t_name
                
        return best_table or (list(tables_dict.keys())[0] if tables_dict else "AlertsDetails")

    def validate_schema_integrity(self, schema: dict) -> list[str]:
        """
        Startup/Build-Time Schema Integrity Safeguard:
        Verifies every table and column referenced in default displays exists in live DB schema.
        Logs loud warnings for missing columns.
        """
        warnings = []
        tables_dict = schema.get("tables", {})
        for t_name, cols_info in tables_dict.items():
            if t_name not in ["AlertsDetails", "CameraList"]:
                continue
            c_names = {c["name"].lower() if isinstance(c, dict) else str(c).lower() for c in cols_info}
            for default_col in config.DEFAULT_DISPLAY_COLUMNS:
                if default_col.lower() not in c_names:
                    msg = f"[SCHEMA INTEGRITY WARNING] Default display column '{default_col}' is missing from live table '{t_name}'."
                    warnings.append(msg)
                    print(msg, flush=True)
        return warnings

    def _deterministic_plan_builder(
        self, query: str, entities: list, intent: str, schema: dict, prior_plan: dict, is_followup: bool
    ) -> dict:
        allowed_set = set(config.ALLOWED_TABLES)
        raw_tables = list(schema.get("tables", {}).keys())
        tables = [t for t in raw_tables if t in allowed_set]
        query_lower = query.lower()

        # Build required column capabilities for dynamic table scoring
        required_capabilities = []
        if any(w in query_lower for w in ["summary", "dashboard", "alert", "alerts"]):
            required_capabilities.extend(["Status", "Severity", "Zone", "Area", "Datetime"])
        if any(w in query_lower for w in ["camera", "cctv"]):
            required_capabilities.extend(["CameraName", "Status", "Url", "Area"])

        for e in entities:
            if e.get("is_resolved") and e.get("matched_column"):
                required_capabilities.append(e["matched_column"])

        if not required_capabilities:
            required_capabilities = ["Status", "Zone", "Area", "Datetime"]

        # Dynamic Table Selection derived from live schema capabilities
        primary_table = self._find_best_table_for_columns(required_capabilities, schema)

        table_cols_info = schema.get("tables", {}).get(primary_table, [])
        table_cols = [c["name"] if isinstance(c, dict) else str(c) for c in table_cols_info]

        # Compute display columns for primary table (exclude internal columns and raw coordinates)
        internal_set = {ic.lower() for ic in config.INTERNAL_COLUMNS}
        select_columns = [c for c in table_cols if c.lower() not in internal_set]
        if not select_columns:
            select_columns = [c for c in table_cols if c in config.DEFAULT_DISPLAY_COLUMNS] or table_cols[:5]

        def resolve_valid_col(raw_col, valid_cols):
            v_lowers = [c.lower() for c in valid_cols]
            r_low = raw_col.lower()
            if r_low in v_lowers:
                return valid_cols[v_lowers.index(r_low)]
            syns = {
                "priority": ["severity", "status"],
                "junction": ["area", "zone", "location"],
                "sensorsubtype": ["alertsubtype", "alerttype", "source"],
                "cameratype": ["alerttype", "source"]
            }
            if r_low in syns:
                for alt in syns[r_low]:
                    if alt in v_lowers:
                        return valid_cols[v_lowers.index(alt)]
            return None

        filters = []
        filtered_cols = set()

        # Generic Sensor-Type Awareness Rule on Sensor_Master
        if primary_table == "Sensor_Master":
            if any(w in query_lower for w in ["camera", "cctv"]):
                filters.append({"table": primary_table, "column": "SensorType", "operator": "=", "value": "Camera"})
                filtered_cols.add("sensortype")
            elif any(w in query_lower for w in ["access control", "accesscontrol"]):
                filters.append({"table": primary_table, "column": "SensorType", "operator": "=", "value": "AccessControl"})
                filtered_cols.add("sensortype")
            elif any(w in query_lower for w in ["sas", "sas sensor"]):
                filters.append({"table": primary_table, "column": "SensorType", "operator": "=", "value": "SAS"})
                filtered_cols.add("sensortype")

            if any(w in query_lower for w in ["offline", "inactive", "non operational", "non-operational", "down", "broken"]):
                filters.append({"table": primary_table, "column": "Status", "operator": "=", "value": "Non Operational"})
                filtered_cols.add("status")
            elif any(w in query_lower for w in ["online", "active", "operational", "working"]):
                filters.append({"table": primary_table, "column": "Status", "operator": "=", "value": "Operational"})
                filtered_cols.add("status")
        for e in entities:
            if e.get("type") in ["date_relative", "date_explicit"]:
                continue
            if e.get("is_resolved") and e.get("matched_column"):
                valid_c = resolve_valid_col(e["matched_column"], table_cols)
                if valid_c:
                    filters.append({
                        "table": primary_table,
                        "column": valid_c,
                        "operator": "=",
                        "value": e["resolved_value"]
                    })
                    filtered_cols.add(valid_c.lower())

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
            cand_order = ["area", "location", "zone"] if ("branch" in query_lower or "branches" in query_lower) else (["zone", "area", "location"] if ("lho" in query_lower or "zone" in query_lower or "zones" in query_lower) else ["area", "zone"])
            for cand in cand_order:
                for c in table_cols:
                    if c.lower() == cand:
                        group_by = [c]
                        break
                if group_by:
                    break
            if not group_by:
                for c in table_cols:
                    if c.lower() not in internal_set and c.lower() not in ["nearestcamera", "alertid", "id"]:
                        group_by = [c]
                        break

        elif intent in ["SUMMARY", "GROUP_BY"] or any(k in query_lower for k in ["summary", "dashboard", "breakdown"]):
            intent = "SUMMARY"
            aggregation = "COUNT"
            limit = None # Aggregated summaries stay uncapped

            # General Rule for SUMMARY Intent:
            # Unless an explicit multi-category breakdown (by branch/severity/type) is requested, SUMMARY intent defaults group_by = ["Status"]
            is_explicit_other_grouping = any(w in query_lower for w in [
                "by branch", "by location", "by area", "by zone", "grouped by branch", "breakdown by branch",
                "breakdown by area", "breakdown by zone", "highest branch", "top branch", "which branch",
                "breakdown by severity", "breakdown by type", "highest number of alerts"
            ])
            if is_explicit_other_grouping:
                cand_order = ["area", "location", "zone"] if "branch" in query_lower else (["zone", "area", "location"] if ("lho" in query_lower or "zone" in query_lower) else ["area", "zone"])
                for cand in cand_order:
                    for c in table_cols:
                        if c.lower() == cand and c.lower() not in filtered_cols:
                            group_by = [c]
                            break
                    if group_by:
                        break
            else:
                status_cols = [c for c in table_cols if c.lower() == "status"]
                group_by = status_cols if status_cols else ["Status"]

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
