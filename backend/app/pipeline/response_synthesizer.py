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

        # Filter out internal/system columns and raw coordinates from display
        internal_set = {ic.lower() for ic in config.INTERNAL_COLUMNS}
        filtered_cols = [c for c in (select_columns or column_names) if c.lower() not in internal_set]
        if not filtered_cols:
            filtered_cols = [c for c in column_names if c.lower() not in internal_set] or column_names

        tot_matching = total_count if total_count is not None else len(rows)

        # Capped listing query header message
        if tot_matching > len(rows):
            header_msg = f"Showing {len(rows)} of {tot_matching:,} matching record(s) — refine your query (by date, location, or status) to narrow this down."
        else:
            header_msg = f"Found {tot_matching:,} matching record(s)."

        # Format clean markdown table as primary summary using filtered display columns only
        table_md = self._format_markdown_table(rows, filtered_cols)

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

        if not nl_summary:
            nl_summary = header_msg

        cleaned_summary = self._post_filter_schema_leakage(nl_summary)
        if cleaned_summary != header_msg and tot_matching > len(rows):
            cleaned_summary = f"{header_msg}\n\n{cleaned_summary}"

        return f"{cleaned_summary}\n\n{table_md}"

    def _post_filter_schema_leakage(self, text: str) -> str:
        """
        Strips internal schema terms like Incident_Data, Master_CamDetails, etc. from response.
        """
        filtered = text
        for term in self.schema_terms:
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            filtered = pattern.sub("system records", filtered)

        # General regex pattern for SQL table like names (e.g. tbl_xxx, col_xxx)
        filtered = re.sub(r'\b[A-Za-z0-9_]+_MASTER\b', 'records', filtered, flags=re.IGNORECASE)
        filtered = re.sub(r'\b[A-Za-z0-9_]+_Data\b', 'records', filtered, flags=re.IGNORECASE)
        return filtered

    def _format_markdown_table(self, rows: list[dict], column_names: list[str]) -> str:
        if not rows or not column_names:
            return ""

        headers = column_names
        header_row = "| " + " | ".join(headers) + " |"
        sep_row = "| " + " | ".join(["---"] * len(headers)) + " |"

        data_rows = []
        for r in rows[:15]:
            vals = [str(r.get(col, "")).replace("|", "\\|") for col in headers]
            data_rows.append("| " + " | ".join(vals) + " |")

        return "\n".join([header_row, sep_row] + data_rows)
