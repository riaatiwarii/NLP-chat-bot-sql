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
        self, user_question: str, rows: list[dict], column_names: list[str], total_count: int = None,
        select_columns: list[str] = None, plan: dict = None, attachments: list[dict] = None
    ) -> str:
        """
        Synthesizes user-friendly answers from database query results.
        """
        if not rows:
            return "No matching records were found in the database for your query."

        # Clean up any un-aliased aggregate keys in rows (e.g. '' or 'count(*)' -> 'TotalAlerts')
        cleaned_rows = []
        for r in rows:
            new_r = {}
            for k, v in r.items():
                key_str = str(k).strip() if k is not None else ""
                if not key_str or key_str.lower() in ["count(*)", "count", "expr1"]:
                    key_str = "TotalAlerts"
                new_r[key_str] = v
            cleaned_rows.append(new_r)
        rows = cleaned_rows

        # Align display columns with actual keys in result rows
        internal_set = {ic.lower() for ic in config.INTERNAL_COLUMNS}
        row_keys = list(rows[0].keys()) if rows else []
        
        # Check if aggregated columns exist
        has_agg = any(any(ak in rk.lower() for ak in ["total", "count", "sum", "avg", "max", "min"]) for rk in row_keys)
        
        if has_agg:
            # For summaries, keep ONLY the grouped dimension(s) and TotalAlerts (compact 2-3 column table)
            dim_cols = [k for k in row_keys if k.lower() not in ["totalalerts", "share", "id", "guid"] and k.lower() not in internal_set]
            matched_headers = (dim_cols if dim_cols else []) + (["TotalAlerts"] if "TotalAlerts" in row_keys else [])
        else:
            candidate_cols = list(select_columns or column_names or row_keys)
            for rk in row_keys:
                if rk not in candidate_cols and rk.lower() not in internal_set:
                    candidate_cols.append(rk)
            filtered_cols = [c for c in candidate_cols if any(rk.lower() == c.lower() for rk in row_keys) and c.lower() not in internal_set]
            matched_headers = []
            for fc in (filtered_cols or row_keys):
                for rk in row_keys:
                    if rk.lower() == fc.lower() and rk not in matched_headers:
                        matched_headers.append(rk)
                        break
            if not matched_headers:
                matched_headers = [rk for rk in row_keys if rk.lower() not in internal_set] or row_keys

        tot_matching = total_count if total_count is not None else len(rows)

        # Capped listing query header message (only for non-aggregated row listings)
        if not has_agg:
            if tot_matching > len(rows):
                header_msg = f"Showing the {len(rows)} most recent matching records (out of {tot_matching:,} total in database)."
            else:
                header_msg = f"Found {tot_matching:,} matching record(s)."
        else:
            header_msg = ""

        # Format clean markdown table as primary summary using filtered display columns only
        table_md = self._format_markdown_table(rows, matched_headers)

        # Extract actual applied filters from plan
        applied_filters = []
        if plan and isinstance(plan.get("filters"), list):
            for f in plan["filters"]:
                if isinstance(f, dict) and f.get("column") and f.get("value"):
                    applied_filters.append(f"{f['column']} = '{f['value']}'")
        applied_filters_str = ", ".join(applied_filters) if applied_filters else "None"

        # Build NL summary prompt
        if has_agg:
            val_col = "TotalAlerts" if "TotalAlerts" in rows[0] else next((k for k in rows[0].keys() if "total" in k.lower() or "count" in k.lower()), None)
            tot_sum = sum(int(r.get(val_col, 0) or 0) for r in rows if str(r.get(val_col, 0)).isdigit()) if val_col else len(rows)
            prompt = (
                f"User Question: {user_question}\n"
                f"Total Count / Alerts: {tot_sum:,}\n"
                f"Filters actually applied in executed SQL: {applied_filters_str}\n"
                f"Breakdown Rows: {json.dumps(rows, default=str)}\n\n"
                f"Summarize the query results into a clear natural language answer. "
                f"CRITICAL: State the exact total count ({tot_sum:,}). "
                f"CRITICAL: Only mention filters that are actually present in the applied filters list ({applied_filters_str}). "
                f"Do NOT say 'across all categories' if the question was filtered to a specific branch or date. "
                "Do NOT invent numbers or facts not in the data. "
                "Do NOT mention internal database table or column names. "
                "Provide the answer directly:\n"
            )
        else:
            prompt = (
                f"User Question: {user_question}\n"
                f"Total Matching Records in Database: {tot_matching:,}\n"
                f"Filters actually applied in executed SQL: {applied_filters_str}\n"
                f"Sample Result Rows (showing {min(len(rows), 5)} of {tot_matching:,}): {json.dumps(rows[:5], default=str)}\n\n"
                f"Summarize the query results into a clear natural language answer. "
                f"CRITICAL: The database contains {tot_matching:,} matching alerts. State: 'Showing the latest {min(len(rows), 5)} matching alerts out of {tot_matching:,} total in database.' "
                f"CRITICAL: Only mention filters that are actually present in the applied filters list ({applied_filters_str}). "
                f"NEVER claim there are only {len(rows)} alerts in the database when total is {tot_matching:,}. "
                "Do NOT invent numbers or facts not in the data. "
                "Do NOT mention internal database table or column names. "
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
            nl_summary = self._build_dynamic_summary(user_question, rows, header_msg, plan=plan)

        cleaned_summary = self._post_filter_schema_leakage(nl_summary)
        if cleaned_summary and header_msg and cleaned_summary != header_msg and tot_matching > len(rows) and not has_agg:
            cleaned_summary = f"{header_msg}\n\n{cleaned_summary}"

        attachments_md = self._format_attachments_section(attachments)

        if not cleaned_summary or cleaned_summary == header_msg:
            body = f"{header_msg}\n\n{table_md}" if header_msg else table_md
        else:
            body = f"{cleaned_summary}\n\n{table_md}"

        return f"{body}\n\n{attachments_md}" if attachments_md else body

    def _format_attachments_section(self, attachments: list[dict]) -> str:
        """
        Renders clickable attachment links (photos/video/docs) for a specific alert.
        Links point at GET /api/attachment/{id}, which decodes the base64-stored file
        from RawAttachments/AlertAttachment and serves it with the right content type.
        The frontend chat renderer already turns markdown [text](url) into a clickable
        link that opens in a new tab - no frontend change needed.
        """
        if not attachments:
            return ""
        lines = ["### 📎 Attachments"]
        for a in attachments:
            att_id = a.get("id")
            try:
                att_id = int(att_id)
            except (TypeError, ValueError):
                pass
            file_name = a.get("file_name") or f"attachment_{att_id}"
            file_type = str(a.get("file_type") or "").lower()
            is_image = any(ext in file_type for ext in ["jpg", "jpeg", "png", "gif", "bmp"])
            icon = "🖼️" if is_image else ("🎥" if "mp4" in file_type or "video" in file_type else "📄")
            lines.append(f"- {icon} [{file_name}](/api/attachment/{att_id})")
        return "\n".join(lines)

    def _build_dynamic_summary(self, question: str, rows: list[dict], default_header: str, plan: dict = None) -> str:
        if not rows:
            return default_header

        q_low = question.lower()
        first_row = rows[0]

        # COUNT(DISTINCT dimension) queries ("how many branches/lhos/alert subtypes are there")
        if plan and (plan.get("intent") == "COUNT_DISTINCT" or plan.get("aggregation") == "COUNT_DISTINCT") and "TotalAlerts" in first_row:
            dim_name = (plan.get("select_columns") or ["value"])[0]
            dim_label = {"LHOCircle": "LHO circles", "AlertSubtype": "alert subtypes", "AlertType": "alert types"}.get(
                dim_name, dim_name.lower() if dim_name.lower().endswith("s") else f"{dim_name.lower()}es"
            )
            return f"There are **{int(first_row['TotalAlerts']):,}** distinct {dim_label}."

        # Ranking / Top / Lowest Query
        if any(k in q_low for k in ["highest", "top", "most", "lowest", "least", "fewest", "minimum"]):
            dim_col = next((k for k in first_row.keys() if k.lower() in ["zone", "area", "location", "branch", "lhocircle", "alerttype", "status", "severity"]), None)
            val_col = next((k for k in first_row.keys() if "total" in k.lower() or "count" in k.lower()), None)
            is_lowest = any(k in q_low for k in ["lowest", "least", "fewest", "minimum"])
            rank_label = "lowest" if is_lowest else "highest"
            if dim_col and val_col:
                top_name = first_row.get(dim_col, "Unknown")
                top_count = first_row.get(val_col, 0)
                dim_title = dim_col if dim_col != "LHOCircle" else "LHO circle"
                return f"The {dim_title.lower()} with the {rank_label} number of alerts is **{top_name}**, with **{top_count:,}** total alerts."

        # Aggregated Status Telemetry Summary Query
        if "TotalAlerts" in first_row or any("count" in k.lower() or "total" in k.lower() for k in first_row.keys()):
            val_col = "TotalAlerts" if "TotalAlerts" in first_row else next(k for k in first_row.keys() if "total" in k.lower() or "count" in k.lower())
            tot_sum = sum(int(r.get(val_col, 0) or 0) for r in rows if str(r.get(val_col, 0)).isdigit())
            dim_col = next((k for k in first_row.keys() if k.lower() in ["status", "area", "zone", "severity", "alerttype", "branch", "lhocircle"]), None)

            if dim_col and dim_col.lower() == "status" and tot_sum > 0:
                pend = sum(int(r.get(val_col, 0) or 0) for r in rows if any(w in str(r.get(dim_col, "")).lower() for w in ["pending", "active", "open"]))
                closed = sum(int(r.get(val_col, 0) or 0) for r in rows if any(w in str(r.get(dim_col, "")).lower() for w in ["closed", "resolved"]))
                ack = sum(int(r.get(val_col, 0) or 0) for r in rows if "ack" in str(r.get(dim_col, "")).lower())

                pend_pct = round((pend / tot_sum) * 100, 2)
                closed_pct = round((closed / tot_sum) * 100, 2)
                ack_pct = round((ack / tot_sum) * 100, 2)

                # Only include location title if filter was actually applied
                loc_title = ""
                if plan:
                    for f in plan.get("filters", []):
                        if (f.get("column") or "").lower() in ["branch", "area", "zone", "lhocircle", "location"]:
                            loc_title = f" for **{f.get('value')}**"
                            break

                return (
                    f"### 📊 Security Alerts Telemetry Breakdown{loc_title}\n\n"
                    f"- **Total Alerts Registered:** `{tot_sum:,}`\n"
                    f"- **Pending / Active Alerts:** `{pend:,}` (`{pend_pct}%` share)\n"
                    f"- **Closed / Resolved Alerts:** `{closed:,}` (`{closed_pct}%` share)\n"
                    f"- **Acknowledged Alerts:** `{ack:,}` (`{ack_pct}%` share)"
                )

            if dim_col and tot_sum > 0:
                breakdowns = [f"{r.get(dim_col, '')} ({int(r.get(val_col, 0)):,})" for r in rows[:4] if r.get(dim_col)]
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
        # Keep newlines as actual newlines for markdown rendering
        val_str = val_str.replace("\r\n", "\n").replace("\n", "\n")
        # Remove existing HTML tags if they cause issues
        val_str = re.sub(r'<br\s*/?>', '\n', val_str)
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

        val_col = next((c for c in headers if any(k in c.lower() for k in ["total", "count"])), None)
        tot_sum = 0
        if val_col:
            tot_sum = sum(int(r.get(val_col, 0) or 0) for r in rows if str(r.get(val_col, 0)).isdigit())

        add_share = bool(val_col and tot_sum > 0 and "Share" not in headers)
        display_headers = list(headers) + (["Share"] if add_share else [])

        header_row = "| " + " | ".join(display_headers) + " |"
        sep_row = "| " + " | ".join(["---"] * len(display_headers)) + " |"

        data_rows = []
        for r in rows[:15]:
            vals = [self._format_value(r.get(col, "")).replace("|", "\\|") for col in headers]
            if add_share:
                cnt = int(r.get(val_col, 0) or 0) if str(r.get(val_col, 0)).isdigit() else 0
                pct = round((cnt / tot_sum) * 100, 2)
                vals.append(f"{pct}%")
            data_rows.append("| " + " | ".join(vals) + " |")

        return "\n".join([header_row, sep_row] + data_rows)
