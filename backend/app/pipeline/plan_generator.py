import json
import copy
import re
import requests
from datetime import datetime, timedelta
from app.config import config

class PlanGenerator:
    """
    Stage 7: Structured Query Plan Generation.

    The LLM is the decision-maker for intent/dimension/filters - it is given the
    live schema, real sample values pulled from the database, and worked examples,
    then trusted to produce the plan. This file does NOT re-decide intent via
    keyword lists after the LLM responds; it only does structural safety checks
    (allowed tables/columns exist, required keys present) and additively merges
    filters the value-resolver already found but the LLM missed. If Ollama is
    unreachable, `_deterministic_plan_builder` is a keyword-based emergency
    fallback so the product still works, but it is not the primary path.
    """
    def __init__(self, distinct_db_values: dict = None):
        self.ollama_host = config.OLLAMA_HOST
        self.ollama_model = config.OLLAMA_RESPONSE_MODEL
        self.distinct_db_values = distinct_db_values or {}

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
        # Skip LLM if disabled - use deterministic rule-based builder only
        if not getattr(config, 'USE_LLM_PLAN_GENERATION', True):
            return self._deterministic_plan_builder(
                normalized_query, resolved_entities, resolved_intent, schema_subset, prior_plan, is_followup
            ), False

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
                    "format": "json",
                    "options": {"temperature": 0.1}
                },
                timeout=config.OLLAMA_TIMEOUT
            )
            if resp.status_code == 200:
                raw_json = resp.json().get("response", "")
                parsed = json.loads(raw_json)
                if isinstance(parsed, dict) and parsed.get("tables_needed"):
                    plan = self._sanitize_llm_plan(parsed, normalized_query, resolved_entities, schema_subset)
                    print(f"[PLAN GENERATOR] LLM plan: {json.dumps(plan)}", flush=True)
                    return plan, False
                print(f"[PLAN GENERATOR WARNING] LLM plan missing required keys, raw: {raw_json[:300]}", flush=True)
        except Exception as e:
            print(f"[PLAN GENERATOR WARNING] Ollama call offline/failed ({e}). Using deterministic plan builder.", flush=True)

        # Fallback Deterministic Plan Builder (Ollama unreachable or produced invalid JSON)
        plan = self._deterministic_plan_builder(
            normalized_query, resolved_entities, resolved_intent, schema_subset, prior_plan, is_followup
        )
        return plan, True

    def _sanitize_llm_plan(self, parsed: dict, query: str, resolved_entities: list, schema_subset: dict) -> dict:
        """
        Structural safety net only - does NOT re-decide intent/dimension.
        1. Restrict tables_needed to ALLOWED_TABLES.
        2. Fill in any missing keys with safe defaults.
        3. Merge resolved entities into filters: add ones the LLM missed, and CORRECT
           ones where the LLM's own value disagrees with a deterministic, exact-match
           resolution (e.g. canonical "resolved"->Closed / "unresolved"->Pending) -
           the value-resolution cascade is a lookup, not a guess, so it wins conflicts.
        4. Drop any filter the LLM invented that isn't backed by a resolved entity and
           doesn't even appear in the question text (anti-hallucination groundedness check).
        """
        parsed["tables_needed"] = [t for t in parsed.get("tables_needed", []) if t in config.ALLOWED_TABLES] or ["vw_AlertReporting"]
        primary_tbl = parsed["tables_needed"][0]
        primary_cols_info = schema_subset.get("tables", {}).get(primary_tbl, [])
        primary_cols = [c["name"] if isinstance(c, dict) else str(c) for c in primary_cols_info]

        parsed.setdefault("filters", [])
        if not isinstance(parsed["filters"], list):
            parsed["filters"] = []
        parsed.setdefault("select_columns", [])
        parsed.setdefault("group_by", None)
        parsed.setdefault("group_by_is_date", False)
        parsed.setdefault("aggregation", None)
        parsed.setdefault("order_by", None)
        parsed.setdefault("limit", None)
        parsed.setdefault("distinct", parsed.get("intent") == "SELECT_DISTINCT")

        # Build column -> trusted resolved value map (only exact/canonical matches, confidence 1.0,
        # from value_resolver.py's deterministic cascade - not fuzzy/embedding guesses).
        trusted_by_col = {}
        for e in resolved_entities:
            if e.get("is_resolved") and e.get("matched_column") and e.get("resolved_value") and e.get("confidence", 0) >= 1.0:
                col = self._resolve_valid_col(e["matched_column"], primary_cols) or e["matched_column"]
                trusted_by_col[col.lower()] = (col, e["resolved_value"])

        query_lower = (query or "").lower()
        kept_filters = []
        for f in parsed["filters"]:
            if not isinstance(f, dict) or not f.get("column"):
                continue
            col_low = f["column"].lower()
            if col_low in trusted_by_col:
                # Deterministic resolution wins any disagreement with the LLM's own value for this column.
                valid_col, trusted_val = trusted_by_col[col_low]
                if str(f.get("value", "")).strip().lower() != str(trusted_val).strip().lower():
                    print(f"[PLAN GENERATOR] Correcting LLM filter {f['column']}='{f.get('value')}' -> '{trusted_val}' (trusted value resolution)", flush=True)
                f["column"] = valid_col
                f["value"] = trusted_val
                kept_filters.append(f)
                continue

            is_groundable = f.get("is_date_cast") or f.get("operator") == "RANGE" or col_low in {"alertid", "id"}
            value_in_query = str(f.get("value", "")).strip().lower() in query_lower
            if is_groundable or value_in_query:
                kept_filters.append(f)
            else:
                print(f"[PLAN GENERATOR] Dropping ungrounded LLM filter {f['column']}='{f.get('value')}' (not asked for, not backed by a resolved entity)", flush=True)
        parsed["filters"] = kept_filters

        # Additive: add any confidently resolved entity the model didn't already filter on.
        existing_cols = {(f.get("column") or "").lower() for f in parsed["filters"]}
        for e in resolved_entities:
            if e.get("is_resolved") and e.get("matched_column") and e.get("resolved_value"):
                valid_col = self._resolve_valid_col(e["matched_column"], primary_cols) or e["matched_column"]
                if valid_col.lower() not in existing_cols:
                    parsed["filters"].append({
                        "table": primary_tbl,
                        "column": valid_col,
                        "operator": "=",
                        "value": e["resolved_value"]
                    })
                    existing_cols.add(valid_col.lower())

        return parsed

    def _build_prompt(
        self, query: str, entities: list, intent: str, schema: dict, prior_plan: dict, is_followup: bool, err: str
    ) -> str:
        allowed_schema = {k: v for k, v in schema.get("tables", {}).items() if k in config.ALLOWED_TABLES}

        # Ground the model with REAL sample values pulled from the live DB for key dimension
        # columns, instead of hardcoding "new delhi -> LHOCircle" style rules in Python.
        dimension_cols = ["Branch", "LHOCircle", "AlertType", "AlertSubtype", "Status", "Severity"]
        sample_values = {}
        for col in dimension_cols:
            vals = self.distinct_db_values.get(col)
            if vals:
                sample_values[col] = sorted(set(vals))[:25]

        prompt_parts = [
            "You are an expert text-to-SQL query planner for a security-alert monitoring system. "
            "Read the user's question carefully - it may be phrased in any way - and output ONLY strict JSON "
            "(no markdown, no commentary) matching this schema:\n\n",
            json.dumps({
                "intent": "SELECT | SELECT_DISTINCT | SUMMARY | COUNT | COUNT_DISTINCT | AVG | SUM | MAX | MIN",
                "tables_needed": ["table_name"],
                "select_columns": ["col_name"],
                "filters": [{"table": "table_name", "column": "col_name", "operator": "=|!=|>|<|>=|<=|LIKE", "value": "val"}],
                "group_by": ["col_name (null if not grouping)"],
                "group_by_is_date": "true only if grouping by calendar day (e.g. 'which day had the most alerts')",
                "aggregation": "COUNT | COUNT_DISTINCT | AVG | SUM | MAX | MIN (null if none)",
                "order_by": "'col ASC' or 'col DESC' (null if none)",
                "limit": "integer or null",
                "distinct": "true only for SELECT_DISTINCT"
            }, indent=2),
            "\n\nINTENT SEMANTICS (this is the part that matters most - get this right):\n",
            "- COUNT: total number of matching alert ROWS. Use for plain 'how many alerts' with no specific dimension named.\n",
            "- COUNT_DISTINCT: the user is asking 'how many <dimension>' where <dimension> is a category/column "
            "(branches, LHOs, alert types, alert subtypes, statuses, severities) - they want the count of UNIQUE "
            "values in that column, NOT the count of alert rows. select_columns = [that column]. Example: "
            "'how many branches are there' means COUNT_DISTINCT of Branch, not COUNT of alerts.\n",
            "- SELECT_DISTINCT: 'list/show all/what are the <dimension>' - return the unique values themselves "
            "(not a count). select_columns = [that column], distinct = true.\n",
            "- SUMMARY: a breakdown/grouping by a dimension ('alerts by branch', 'breakdown by severity'), or a "
            "ranking question ('which branch has the most alerts', 'which day had the most alerts' - the latter "
            "groups by calendar date, so set group_by_is_date = true and group_by to the date/time column).\n",
            "- Distinguish AlertType (e.g. VMS, CCTV, Analytics, ATM - the sensor/source category) from "
            "AlertSubtype (e.g. Motion, Tamper, Device Alert - the specific trigger). A question mentioning "
            "'sub type'/'subtype' means AlertSubtype, not AlertType.\n",
            "- A place name (e.g. a city, or an LHO circle name) should be matched against whichever REAL sample "
            "values below it actually appears in - do not guess which column it belongs to.\n",
            "- If the question both names a dimension to count/list AND mentions a specific location/filter value "
            "(e.g. 'how many branches are there in new delhi'), keep BOTH: the dimension drives intent/select_columns, "
            "the location becomes a filter.\n",
            "- Status vocabulary: 'resolved'/'closed'/'completed' -> Status = 'Closed'. 'unresolved'/'pending'/"
            "'open'/'active' -> Status = 'Pending'. Never reverse these.\n\n",
            f"### Live database schema (allowed tables/columns only):\n{json.dumps(allowed_schema)}\n\n",
        ]

        if sample_values:
            prompt_parts.append(
                "### Real sample values from the live database for key columns "
                "(use these to decide which column a place/category name belongs to):\n"
                f"{json.dumps(sample_values, indent=2)}\n\n"
            )

        prompt_parts.append(self._few_shot_examples())

        prompt_parts.extend([
            f"### User Question: {query}\n",
            f"Entities already resolved by the pipeline (values matched against the live DB - trust these over "
            f"your own reading of the text for the exact filter value): {json.dumps(entities, default=str)}\n",
        ])
        if is_followup and prior_plan:
            prompt_parts.append(
                f"This is a FOLLOW-UP to a prior turn. Prior plan: {json.dumps(prior_plan)}\n"
                "Update/diff the prior plan against the new question - keep prior filters that still apply, "
                "replace ones the new question overrides, drop ones it doesn't mention only if the new "
                "question clearly changes topic.\n"
            )
        if err:
            prompt_parts.append(f"Your previous attempt was invalid: {err}\nFix this specific problem.\n")

        prompt_parts.append("\nJSON Output:")
        return "".join(prompt_parts)

    def _few_shot_examples(self) -> str:
        examples = [
            ("how many branches are there",
             {"intent": "COUNT_DISTINCT", "tables_needed": ["vw_AlertReporting"], "select_columns": ["Branch"],
              "filters": [], "group_by": None, "aggregation": "COUNT_DISTINCT", "limit": None}),
            ("list all lhos",
             {"intent": "SELECT_DISTINCT", "tables_needed": ["vw_AlertReporting"], "select_columns": ["LHOCircle"],
              "filters": [], "distinct": True, "limit": None}),
            ("how many sub types of alert are there",
             {"intent": "COUNT_DISTINCT", "tables_needed": ["vw_AlertReporting"], "select_columns": ["AlertSubtype"],
              "filters": [], "aggregation": "COUNT_DISTINCT", "limit": None}),
            ("how many branches are there in new delhi",
             {"intent": "COUNT_DISTINCT", "tables_needed": ["vw_AlertReporting"], "select_columns": ["Branch"],
              "filters": [{"table": "vw_AlertReporting", "column": "LHOCircle", "operator": "LIKE", "value": "NEW DELHI"}],
              "aggregation": "COUNT_DISTINCT", "limit": None}),
            ("which day has the maximum alerts",
             {"intent": "SUMMARY", "tables_needed": ["vw_AlertReporting"], "select_columns": ["Datetime", "TotalAlerts"],
              "filters": [], "group_by": ["Datetime"], "group_by_is_date": True, "aggregation": "COUNT",
              "order_by": "TotalAlerts DESC", "limit": 1}),
            ("resolved alerts summary",
             {"intent": "SUMMARY", "tables_needed": ["vw_AlertReporting"], "select_columns": ["Status", "TotalAlerts"],
              "filters": [{"table": "vw_AlertReporting", "column": "Status", "operator": "=", "value": "Closed"}],
              "group_by": ["Status"], "aggregation": "COUNT", "limit": None}),
            ("how many alerts in agra",
             {"intent": "COUNT", "tables_needed": ["vw_AlertReporting"], "select_columns": ["TotalAlerts"],
              "filters": [{"table": "vw_AlertReporting", "column": "Branch", "operator": "LIKE", "value": "AGRA"}],
              "aggregation": "COUNT", "limit": None}),
            ("top 5 branches with the highest alerts",
             {"intent": "SUMMARY", "tables_needed": ["vw_AlertReporting"], "select_columns": ["Branch", "TotalAlerts"],
              "filters": [], "group_by": ["Branch"], "aggregation": "COUNT", "order_by": "TotalAlerts DESC", "limit": 5}),
        ]
        lines = ["### Worked examples:\n"]
        for q, plan in examples:
            lines.append(f"Q: {q}\nA: {json.dumps(plan)}\n")
        lines.append("\n")
        return "".join(lines)

    def _find_best_table_for_columns(self, required_cols: list[str], schema: dict) -> str:
        """
        Dynamic Schema-Driven Table Routing Rule:
        Scores live introspected tables against required column capabilities.
        Routes to whichever table actually possesses the required columns in the live DB schema.
        Prefer vw_AlertReporting for general alert queries.
        """
        allowed_set = set(config.ALLOWED_TABLES)
        tables_dict = schema.get("tables", {})

        if "vw_AlertReporting" in tables_dict and "vw_AlertReporting" in allowed_set:
            return "vw_AlertReporting"

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

        return best_table or (list(tables_dict.keys())[0] if tables_dict else "vw_AlertReporting")

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

    def _parse_single_date(self, text_str: str, default_year: int = 2026) -> datetime.date:
        if not text_str:
            return None
        import re
        from datetime import datetime, timedelta
        text_clean = text_str.lower().strip()
        month_map = {
            "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
            "apr": 4, "april": 4, "may": 5, "june": 6, "jul": 7, "july": 7,
            "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
            "nov": 11, "november": 11, "dec": 12, "december": 12
        }

        # 1. ISO YYYY-MM-DD
        iso_m = re.search(r'\b(\d{4})-(\d{2})-(\d{2})\b', text_clean)
        if iso_m:
            try:
                return datetime.strptime(iso_m.group(0), "%Y-%m-%d").date()
            except Exception:
                pass

        # 2. DD/MM/YYYY
        slash_m = re.search(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b', text_clean)
        if slash_m:
            try:
                return datetime.strptime(slash_m.group(0), "%d/%m/%Y").date()
            except Exception:
                pass

        # 3. DD Month (YYYY)
        m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)(?:\s+(\d{4}))?\b', text_clean)
        if m:
            d_num = int(m.group(1))
            m_num = month_map.get(m.group(2).lower())
            y_num = int(m.group(3)) if m.group(3) else default_year
            try:
                return datetime(y_num, m_num, d_num).date()
            except Exception:
                pass

        # 4. Month DD (YYYY)
        m2 = re.search(r'\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?\b', text_clean)
        if m2:
            m_num = month_map.get(m2.group(1).lower())
            d_num = int(m2.group(2))
            y_num = int(m2.group(3)) if m2.group(3) else default_year
            try:
                return datetime(y_num, m_num, d_num).date()
            except Exception:
                pass

        return None

    def parse_date_expression(self, text: str) -> dict:
        """
        Parses relative, text, date range, and explicit date expressions from query text.
        Returns dict with {"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "label": str, "is_valid": bool} or None.
        """
        if not text:
            return None
        import re
        text_low = text.lower().strip()
        from datetime import datetime, timedelta

        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(config.TIMEZONE)
        except Exception:
            tz = None

        today = datetime.now(tz).date() if tz else datetime.now().date()

        # 1. Check Date Range Expressions (e.g. "between 10 July and 15 July 2026", "from 10 July to 15 July")
        range_match = re.search(r'\b(?:between|from)\s+(.+?)\s+(?:and|to|-)\s+(.+?)(?:\s+(?:in|for|at|with|where|order|group|limit)\b|$)', text_low)
        if not range_match:
            range_match = re.search(r'\b(\d{1,2}(?:st|nd|rd|th)?\s+[a-z]+(?:\s+\d{4})?)\s*(?:to|-)\s*(\d{1,2}(?:st|nd|rd|th)?\s+[a-z]+(?:\s+\d{4})?)\b', text_low)

        if range_match:
            d1_raw, d2_raw = range_match.group(1).strip(), range_match.group(2).strip()
            # Check if year is mentioned anywhere in the query
            year_match = re.search(r'\b(20\d\d)\b', text_low)
            query_year = int(year_match.group(1)) if year_match else 2026

            dt2 = self._parse_single_date(d2_raw, default_year=query_year)
            dt1 = self._parse_single_date(d1_raw, default_year=query_year)
            if not dt1 and dt2 and re.match(r'^\d{1,2}(?:st|nd|rd|th)?$', d1_raw):
                try:
                    d1_day = int(re.sub(r'\D', '', d1_raw))
                    dt1 = dt2.replace(day=d1_day)
                except Exception:
                    pass
            if not dt2 and dt1 and re.match(r'^\d{1,2}(?:st|nd|rd|th)?$', d2_raw):
                try:
                    d2_day = int(re.sub(r'\D', '', d2_raw))
                    dt2 = dt1.replace(day=d2_day)
                except Exception:
                    pass

            if dt1 and dt2:
                if dt1 > dt2:
                    dt1, dt2 = dt2, dt1
                start_str = dt1.strftime("%Y-%m-%d")
                end_str = (dt2 + timedelta(days=1)).strftime("%Y-%m-%d")
                return {"start_date": start_str, "end_date": end_str, "label": "date_range", "is_range": True, "is_valid": True}

        # 2. Relative Range Expressions
        if any(w in text_low for w in ["last week", "past week", "last 7 days", "past 7 days", "this week"]):
            start = today - timedelta(days=7)
            end = today + timedelta(days=1)
            return {"start_date": start.strftime("%Y-%m-%d"), "end_date": end.strftime("%Y-%m-%d"), "label": "last_7_days", "is_range": True, "is_valid": True}

        if any(w in text_low for w in ["last month", "past month", "this month", "last 30 days", "past 30 days"]):
            start = today - timedelta(days=30)
            end = today + timedelta(days=1)
            return {"start_date": start.strftime("%Y-%m-%d"), "end_date": end.strftime("%Y-%m-%d"), "label": "last_30_days", "is_range": True, "is_valid": True}

        if "today" in text_low:
            start_str = today.strftime("%Y-%m-%d")
            end_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")
            return {"start_date": start_str, "end_date": end_str, "label": "today", "is_range": True, "is_valid": True}

        if "yesterday" in text_low:
            yest = today - timedelta(days=1)
            start_str = yest.strftime("%Y-%m-%d")
            end_str = today.strftime("%Y-%m-%d")
            return {"start_date": start_str, "end_date": end_str, "label": "yesterday", "is_range": True, "is_valid": True}

        # Day of week matching (e.g. "last Tuesday", "last Monday")
        days_of_week = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for idx, day_name in enumerate(days_of_week):
            if day_name in text_low:
                current_dow = today.weekday()
                target_dow = idx
                days_ago = (current_dow - target_dow) % 7
                if days_ago == 0 or "last" in text_low:
                    days_ago = days_ago if (days_ago > 0 and "last" not in text_low) else (days_ago + 7 if days_ago == 0 else days_ago)
                target_date = today - timedelta(days=days_ago)
                start_str = target_date.strftime("%Y-%m-%d")
                end_str = (target_date + timedelta(days=1)).strftime("%Y-%m-%d")
                return {"start_date": start_str, "end_date": end_str, "label": day_name, "is_range": True, "is_valid": True}

        # 3. Single Specific Date (default dataset year 2026)
        year_match = re.search(r'\b(20\d\d)\b', text_low)
        query_year = int(year_match.group(1)) if year_match else 2026
        dt_single = self._parse_single_date(text_low, default_year=query_year)
        if dt_single:
            start_str = dt_single.strftime("%Y-%m-%d")
            end_str = (dt_single + timedelta(days=1)).strftime("%Y-%m-%d")
            return {"start_date": start_str, "end_date": end_str, "label": f"{dt_single.day}_{dt_single.month}", "is_range": True, "is_valid": True}

        return None

    def _resolve_valid_col(self, raw_col: str, valid_cols: list[str]) -> str:
        if not raw_col:
            return None
        clean_col = raw_col.split(".")[-1] # Strip table prefix
        v_lowers = [c.lower() for c in valid_cols]
        r_low = clean_col.lower()
        if r_low in v_lowers:
            return valid_cols[v_lowers.index(r_low)]
        syns = {
            "priority": ["severity", "status"],
            "junction": ["branch", "area", "lhocircle", "zone", "location"],
            "sensorsubtype": ["alertsubtype", "alerttype", "source"],
            "cameratype": ["alerttype", "source"],
            "area": ["branch", "area"],
            "branch": ["branch", "area"],
            "zone": ["lhocircle", "zone"],
            "lho": ["lhocircle", "zone"],
            "lhocircle": ["lhocircle", "zone"],
            "alerttype": ["alerttype", "type", "alert_type"],
            "status": ["status"],
            "severity": ["severity"]
        }
        if r_low in syns:
            for alt in syns[r_low]:
                if alt in v_lowers:
                    return valid_cols[v_lowers.index(alt)]
        return None

    def _deterministic_plan_builder(
        self, query: str, entities: list, intent: str, schema: dict, prior_plan: dict, is_followup: bool
    ) -> dict:
        """
        EMERGENCY FALLBACK ONLY - used when Ollama is unreachable or returns invalid JSON.
        Keyword-based and intentionally conservative; the LLM path in generate_plan() above
        is the primary decision-maker for intent/dimension resolution.
        """
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
        # Prioritize vw_AlertReporting for alert-related queries (has better LHO/Branch data)
        if any(w in query_lower for w in ["alert", "alerts", "summary", "dashboard", "incident", "incidents"]):
            if "vw_AlertReporting" in schema.get("tables", {}):
                primary_table = "vw_AlertReporting"
            else:
                primary_table = self._find_best_table_for_columns(required_capabilities, schema)
        else:
            primary_table = self._find_best_table_for_columns(required_capabilities, schema)

        table_cols_info = schema.get("tables", {}).get(primary_table, [])
        table_cols = [c["name"] if isinstance(c, dict) else str(c) for c in table_cols_info]

        # Compute display columns for primary table (exclude internal columns and raw coordinates)
        internal_set = {ic.lower() for ic in config.INTERNAL_COLUMNS}
        select_columns = [c for c in table_cols if c.lower() not in internal_set]
        if not select_columns:
            select_columns = [c for c in table_cols if c in config.DEFAULT_DISPLAY_COLUMNS] or table_cols[:5]

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
            elif any(w in query_lower for w in ["pending", "unresolved"]):
                filters.append({"table": primary_table, "column": "Status", "operator": "=", "value": "Pending"})
                filtered_cols.add("status")
            elif any(w in query_lower for w in ["closed", "resolved"]):
                filters.append({"table": primary_table, "column": "Status", "operator": "=", "value": "Closed"})
                filtered_cols.add("status")

        # Preserve ALL resolved entities (AlertType, Status, Branch, Severity, LHOCircle, AlertID)
        for e in entities:
            if e.get("type") in ["date_relative", "date_explicit"] or e.get("resolution_step") in ["date_month_token", "unresolved_structural_keyword"]:
                continue
            if e.get("is_resolved") and e.get("matched_column") and e.get("resolved_value"):
                valid_c = self._resolve_valid_col(e["matched_column"], table_cols)
                if valid_c and valid_c.lower() not in filtered_cols:
                    filters.append({
                        "table": primary_table,
                        "column": valid_c,
                        "operator": "=",
                        "value": e["resolved_value"]
                    })
                    filtered_cols.add(valid_c.lower())

        # Timezone-aware Date Filter Resolution (ALWAYS runs for ALL queries and intents)
        date_col = None
        for c in table_cols:
            if c.lower() in ["createdtime", "datetime", "timestamp", "createddate", "alertcreateime", "time"]:
                date_col = c
                break

        if date_col and not any(f["column"].lower() == date_col.lower() for f in filters):
            parsed_d = self.parse_date_expression(query)
            if parsed_d and parsed_d.get("is_valid"):
                filters.append({
                    "table": primary_table,
                    "column": date_col,
                    "operator": "RANGE",
                    "start_date": parsed_d["start_date"],
                    "end_date": parsed_d["end_date"],
                    "value": parsed_d["start_date"],
                    "is_date_cast": True
                })

        # Context-Sensitive Group-By & Ranking Selection
        group_by = None
        aggregation = intent if intent not in ["SELECT", "SUMMARY", "SELECT_DISTINCT"] else None
        limit = config.LIST_QUERY_ROW_LIMIT if intent in ["SELECT", "SELECT_DISTINCT"] else None
        order_by = None
        distinct = False
        group_by_is_date = False

        # Identify requested dimension if query specifies one
        detected_dim = None
        if any(w in query_lower for w in ["sub type", "sub-type", "subtype", "alertsubtype", "alert subtype"]):
            detected_dim = "AlertSubtype"
        elif any(w in query_lower for w in ["which day", "what day", "by day", "each day", "per day"]):
            detected_dim = "__DATE__"
        elif any(w in query_lower for w in ["alert type", "alert types", "alerttype", "alerttypes", "by type", "by alert type", "type occurs", "types occur", "types of alert", "types of alerts", "type of alert"]):
            detected_dim = "AlertType"
        elif any(w in query_lower for w in ["branch", "branches", "by branch", "branch wise", "which branch"]):
            detected_dim = "Branch"
        elif any(w in query_lower for w in ["lho", "lhos", "circle", "zone", "zones", "by lho", "by zone", "which lho"]):
            detected_dim = "LHOCircle"
        elif any(w in query_lower for w in ["status", "by status", "by their status", "status wise"]):
            detected_dim = "Status"
        elif any(w in query_lower for w in ["severity", "by severity", "severity wise"]):
            detected_dim = "Severity"

        def resolve_dim(dim_name):
            """Returns (column_name, is_date) - resolves __DATE__ to an actual date column."""
            if dim_name == "__DATE__":
                for c in table_cols:
                    if c.lower() in ["datetime", "createdtime", "timestamp", "createddate", "time"]:
                        return c, True
                dim_name = "Branch"
            return (self._resolve_valid_col(dim_name, table_cols) or dim_name), False

        has_real_dim = detected_dim is not None

        is_lowest_query = any(k in query_lower for k in ["lowest", "least", "fewest", "smallest", "minimum", "occurs least", "least alerts", "lowest alerts"])
        is_highest_query = any(k in query_lower for k in ["highest", "most", "top", "maximum", "occurs most", "most alerts", "highest alerts"])

        # 1. "How many <dimension>" = COUNT(DISTINCT dimension), not COUNT(*) of every alert row.
        if has_real_dim and any(k in query_lower for k in ["how many", "count of", "total number of", "total number", "cnt", "kount"]) and not (is_lowest_query or is_highest_query):
            intent = "COUNT_DISTINCT"
            aggregation = "COUNT_DISTINCT"
            target_col, group_by_is_date = resolve_dim(detected_dim)
            select_columns = [target_col]
            limit = None

        elif (intent == "COUNT" or any(k in query_lower for k in ["how many", "count of", "total number of", "total number", "cnt", "kount"])) and not (is_lowest_query or is_highest_query):
            intent = "COUNT"
            aggregation = "COUNT"
            group_by = None
            select_columns = ["TotalAlerts"]
            limit = None

        # 2. "List all / show all <dimension>" = the distinct values themselves.
        elif (
            intent == "SELECT_DISTINCT"
            or (has_real_dim and re.search(r'\b(?:list|show|get|view)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?(?:lhos?|branch(?:es)?|zone[s]?|jurisdiction[s]?|alert\s*sub\s*type[s]?|alert\s*type[s]?|status(?:es)?|severit(?:y|ies))\b', query_lower))
        ) and not (is_lowest_query or is_highest_query):
            intent = "SELECT_DISTINCT"
            distinct = True
            limit = None
            target_col, _ = resolve_dim(detected_dim or "Branch")
            select_columns = [target_col]

        # 3. Ranking Queries: Lowest / Least / Highest / Most
        elif is_lowest_query or is_highest_query:
            intent = "SUMMARY"
            aggregation = "COUNT"
            order_by = "TotalAlerts ASC" if is_lowest_query else "TotalAlerts DESC"
            limit = 1 if any(w in query_lower for w in ["which", "lowest", "least", "highest", "most", "top 1"]) else 5

            valid_dim, group_by_is_date = resolve_dim(detected_dim or "Branch")
            group_by = [valid_dim]
            select_columns = [valid_dim, "TotalAlerts"]

        # 4. Group By / Summary Queries ("alerts by their status", "breakdown by severity", "alerts summary")
        elif intent in ["SUMMARY", "GROUP_BY"] or any(k in query_lower for k in ["summary", "dashboard", "breakdown", "distribution", "by "]):
            intent = "SUMMARY"
            aggregation = "COUNT"
            limit = None # Aggregated summaries stay uncapped

            if detected_dim:
                valid_dim, group_by_is_date = resolve_dim(detected_dim)
                group_by = [valid_dim]
            else:
                # Default for generic summary (e.g. "show alert summary for agra")
                has_loc_filter = any(
                    (f.get("column") or "").lower() in ["branch", "area", "zone", "lhocircle", "location"]
                    for f in filters
                )
                if has_loc_filter:
                    group_by = [self._resolve_valid_col("Status", table_cols) or "Status"]
                else:
                    group_by = [self._resolve_valid_col("Branch", table_cols) or "Branch"]

            select_columns = list(group_by) + ["TotalAlerts"]

        if intent == "SUMMARY" and group_by:
            select_columns = list(group_by) + ["TotalAlerts"]

        if any(k in query_lower for k in ["recent", "latest", "newest"]) and not group_by:
            order_by = "Datetime DESC" if "datetime" in [c.lower() for c in table_cols] else "CreatedTime DESC"

        # Follow-up diffing: update filters from prior turn
        if is_followup and prior_plan:
            base_plan = copy.deepcopy(prior_plan)
            base_plan["intent"] = intent
            base_plan["select_columns"] = select_columns
            base_plan["limit"] = limit
            base_plan["order_by"] = order_by
            base_plan["distinct"] = distinct
            base_plan["group_by_is_date"] = group_by_is_date

            # Remove single-record AlertID filter if new query doesn't specify an AlertID
            if not any(k in query_lower for k in ["alertid", "alert id", "id"]):
                base_plan["filters"] = [f for f in base_plan.get("filters", []) if f.get("column", "").lower() not in ["alertid", "id"]]

            if filters:
                existing_cols = {f["column"].lower(): i for i, f in enumerate(base_plan.get("filters", []))}
                for new_f in filters:
                    new_col_key = new_f["column"].lower()
                    if new_col_key in existing_cols:
                        base_plan["filters"][existing_cols[new_col_key]] = new_f
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
            "distinct": distinct,
            "group_by_is_date": group_by_is_date
        }
