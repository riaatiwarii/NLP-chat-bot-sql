import re
import json
import requests
from app.config import config

class ResponseSynthesizer:
    """
    Stage 14: Natural Language Response Synthesis
    Synthesizes user-friendly answers from database query results.
    Includes regex post-filter backup check against internal database schema term leakage.
    """
    def __init__(self, schema_table_names: list[str] = None):
        self.ollama_host = config.OLLAMA_HOST
        self.ollama_model = config.OLLAMA_RESPONSE_MODEL
        self.schema_terms = schema_table_names or [
            "Incident_Data", "CameraList", "AlertsDetails", "Master_CamDetails", "Location_Master", "SOP_MASTER"
        ]

    def synthesize(
        self, user_question: str, rows: list[dict], column_names: list[str], total_count: int = None, select_columns: list[str] = None
    ) -> str:
        """
        Synthesizes response text.
        """
        if not rows:
            return "No matching records were found in the database for your query."

        # Align display columns with actual keys in result rows
        internal_set = {ic.lower() for ic in config.INTERNAL_COLUMNS}
        row_keys = list(rows[0].keys()) if rows else []
        
        # Use row_keys if select_columns/column_names contain keys missing from rows
        candidate_cols = select_columns or column_names or row_keys
        filtered_cols = [c for c in candidate_cols if any(rk.lower() == c.lower() for rk in row_keys) and c.lower() not in internal_set]
        
        if not filtered_cols:
            filtered_cols = [rk for rk in row_keys if rk.lower() not in internal_set] or row_keys

        # Match exact casing from row_keys
        matched_headers = []
        for fc in filtered_cols:
            for rk in row_keys:
                if rk.lower() == fc.lower():
                    matched_headers.append(rk)
                    break
        if not matched_headers:
            matched_headers = row_keys

        tot_matching = total_count if total_count is not None else len(rows)

        # Capped listing query header message
        if tot_matching > len(rows):
            header_msg = f"Showing {len(rows)} of {tot_matching:,} matching record(s) — refine your query (by date, location, or status) to narrow this down."
        else:
            header_msg = f"Found {tot_matching:,} matching record(s)."

        # Format clean markdown table as primary summary using filtered display columns only
        table_md = self._format_markdown_table(rows, matched_headers)

        # Build NL summary prompt
        prompt = (
            f"User Question: {user_question}\n"
            f"Database Result Rows: {json.dumps(rows[:5], default=str)}\n\n"
            "Summarize the query results into a clear natural language answer. "
            "Do NOT invent numbers or facts not in the data. "
            "Do NOT mention internal database table or column names (e.g. Incident_Data, CameraId, cam_status). "
            "Provide the answer directly:\n"
        )

        nl_summary = ""
        try:
            resp = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2}
                },
                timeout=config.OLLAMA_TIMEOUT
            )
            if resp.status_code == 200:
                nl_summary = resp.json().get("response", "").strip()
        except Exception:
            pass

        if not nl_summary or "99" in nl_summary:
            nl_summary = self._build_dynamic_summary(user_question, rows, header_msg)

        cleaned_summary = self._post_filter_schema_leakage(nl_summary)
        if cleaned_summary != header_msg and tot_matching > len(rows):
            cleaned_summary = f"{header_msg}\n\n{cleaned_summary}"

        return f"{cleaned_summary}\n\n{table_md}"

    def _build_dynamic_summary(self, question: str, rows: list[dict], default_header: str) -> str:
        if not rows:
            return default_header

        q_low = question.lower()
        first_row = rows[0]

        # Ranking / Top Branch Query
        if any(k in q_low for k in ["highest", "top", "most"]):
            dim_col = next((k for k in first_row.keys() if k.lower() in ["zone", "area", "location", "branch"]), None)
            val_col = next((k for k in first_row.keys() if "total" in k.lower() or "count" in k.lower()), None)
            if dim_col and val_col:
                top_name = first_row.get(dim_col, "Unknown")
                top_count = first_row.get(val_col, 0)
                return f"The branch/zone with the highest number of alerts is **{top_name}**, with **{top_count:,}** total alerts."

        # Aggregated Summary Query
        if "TotalAlerts" in first_row or any("count" in k.lower() for k in first_row.keys()):
            tot_sum = sum(int(r.get("TotalAlerts", 0) or 0) for r in rows if str(r.get("TotalAlerts", 0)).isdigit())
            dim_col = next((k for k in first_row.keys() if k.lower() in ["area", "zone", "status", "severity", "alerttype"]), None)
            if dim_col and tot_sum > 0:
                breakdowns = [f"{r.get(dim_col, '')} ({int(r.get('TotalAlerts', 0)):,})" for r in rows[:4] if r.get(dim_col)]
                bd_str = ", ".join(breakdowns)
                return f"Total summary shows **{tot_sum:,}** total alerts across {len(rows)} categories ({bd_str})."

        return default_header

    def _post_filter_schema_leakage(self, text: str) -> str:
        """
        Strips internal schema terms like Incident_Data, Master_CamDetails, etc. from response.
        """
        filtered = text
        for term in self.schema_terms:
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            filtered = pattern.sub("system records", filtered)

        filtered = re.sub(r'\b[A-Za-z0-9_]+_MASTER\b', 'records', filtered, flags=re.IGNORECASE)
        filtered = re.sub(r'\b[A-Za-z0-9_]+_Data\b', 'records', filtered, flags=re.IGNORECASE)
        return filtered

    def _format_value(self, val) -> str:
        if val is None or str(val).strip() == "":
            return ""
        from datetime import datetime
        if isinstance(val, datetime):
            return val.strftime("%d %b %Y, %I:%M %p")
        val_str = str(val).strip()
        # Exclude raw lat/long coordinate strings
        if re.match(r'^\d+\.\d+,\d+\.\d+$', val_str):
            return ""
        # Match ISO datetime string pattern (e.g. 2026-07-28T11:21:22.850000 or 2026-07-28 11:21:22)
        iso_match = re.match(r'^(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2}:\d{2})(?:\.\d+)?$', val_str)
        if iso_match:
            try:
                dt = datetime.fromisoformat(val_str.replace("Z", ""))
                return dt.strftime("%d %b %Y, %I:%M %p")
            except Exception:
                pass
        return val_str

    def _format_markdown_table(self, rows: list[dict], column_names: list[str]) -> str:
        if not rows or not column_names:
            return ""

        headers = [c for c in column_names if c.lower() != "location"]
        header_row = "| " + " | ".join(headers) + " |"
        sep_row = "| " + " | ".join(["---"] * len(headers)) + " |"

        data_rows = []
        for r in rows[:15]:
            vals = [self._format_value(r.get(col, "")).replace("|", "\\|") for col in headers]
            data_rows.append("| " + " | ".join(vals) + " |")

        return "\n".join([header_row, sep_row] + data_rows)
