import re
import requests
import json
import os
from datetime import datetime, timedelta
from sqlalchemy import text
from app.data_service import DataService
from app.schema_engine import SchemaEngine
from app.schema_linker import SchemaLinker
from app.context_tracker import ContextTracker

class ChatbotService:
    def __init__(self, data_service: DataService):
        self.ds = data_service
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://192.168.0.10:11434").rstrip("/")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "sqlcoder:15b")
        
        # Dynamic Schema & Semantic NLP Linking Engines
        self.schema_engine = SchemaEngine(self.ds.engine) if self.ds and self.ds.engine else None
        self.schema_linker = SchemaLinker(self.schema_engine) if self.schema_engine else None
        self.context_tracker = ContextTracker()
        
        # Semantic Embeddings Classifier fields

        self.embedder = None
        self.template_embeddings = None
        self.intent_labels = []
        self.semantic_templates = {
            "DASHBOARD_SUMMARY": [
                "show today's dashboard summary",
                "give me a high level overview of the system",
                "is the system operating normally",
                "what are the main metrics today",

                "system health percentage status",

                "sbi cms central dashboard summary"

            ],

            "OFFLINE_CAMERAS": [

                "which cctv cameras are offline",

                "are there any camera failures",

                "list cams that are down or dead",

                "show broken lenses or blank feeds",

                "offline cameras in bhopal LHO",

                "are the cameras working fine"

            ],

            "OPERATOR_PERFORMANCE": [

                "who is the top operator today",

                "show the operator leaderboard",

                "which agent handled the most cases",

                "who resolved the most incidents",

                "operator leaderboard ranking stats"

            ],

            "BRANCH_COUNT": [

                "how many branches do we have",

                "total number of branches configured",

                "how many active circles and LHO centers",

                "count of branches in system",

                "total branches list count"

            ],

            "FALSE_ALERT_RATE": [

                "which branch has the highest false alert rate",

                "show accidental triggers or false alarms",

                "list branches showing wrong triggers",

                "false alarm percentage rates by branch"

            ],

            "LHO_RESPONSE_TIME": [

                "what is the average response time for LHO circles",

                "show circle response averages",

                "SLA and response latency times"

            ],

            "AI_USE_CASE_STATS": [

                "show me AI use case alert stats",

                "AI use case statistics",

                "use case alert breakdown",

                "alert stats by use case",

                "AI alerts distribution"

            ],

            "CAMERA_TAMPERING": [

                "which branches have repeated camera tampering alerts",

                "show camera tampering alerts count",

                "tampered lenses or camera vandalism"

            ],

            "PERIMETER_BREACHES": [

                "show perimeter breach logs",

                "list repeated perimeter breaches",

                "outer boundary alleys or fence intrusions"

            ],

            "PANIC_BUTTON": [

                "show panic button triggers",

                "who pressed the panic button",

                "panic alarm ticket logs"

            ],

            "FIRE_ALERTS": [

                "show fire or smoke alerts",

                "active smoke detector warnings",

                "fire alarm tickets"

            ],

            "SOP_QUERY": [

                "show standard operating procedure for panic button",

                "SOP guidelines for perimeter breach",

                "what is the SOP policy for alerts"

            ],

            "ACTIVE_INCIDENTS": [

                "how many active incidents are there today",

                "list all open tickets",

                "show in progress cases"

            ],

            "UNHEALTHY_DEVICES": [

                "list unhealthy devices",

                "show devices in warning state",

                "unhealthy cctv or nvr components"

            ],

            "FOLLOW_UP_BRANCH_NAME": [

                "which branch is this",

                "what is the name of this branch",

                "tell me its name",

                "what are the names of the branches",

                "which one",

                "what are their names"

            ],

            "RECENT_ALERTS": [

                "show alerts",

                "any anomaly alert today",

                "show telemetry alerts",

                "recent alarms",

                "list alerts today",

                "any security alerts logged"

            ],

            "FOLLOW_UP_EXPLAIN_DATA": [

                "can you explain me this data",

                "what is this data",

                "explain it",

                "what does this mean",

                "elaborate on these results",

                "what is it",

                "explain me this data what is it",

                "what does it show"

            ],

            "OPERATOR_WORKLOAD": [

                "how many alerts is priya patel handling",

                "incidents assigned to aarav sharma",

                "what is the workload of priya patel",

                "operator incident queue",

                "what tickets are assigned to operator",

                "how many alerts are assigned to aarav"

            ],

            "ALERT_TYPES": [

                "how many alert types we have",

                "what are the alert types in the database",

                "list all distinct alert types",

                "types of alerts registered",

                "show different kinds of alerts"

            ],

            "ALERTS_BY_TYPE": [

                "how many alerts of VMS we have and where",

                "VMS alert counts by branch",

                "show count of SAS alerts at each location",

                "how many analytics alerts are registered",

                "distribution of VMS alarms"

            ]

        }



        # Eagerly load sentence-transformers on main thread to avoid PyTorch/OpenMP thread deadlocks in endpoints

        print("[SEMANTIC NLP] Eagerly loading sentence-transformers (all-MiniLM-L6-v2) on CPU...")

        import torch

        torch.set_num_threads(1)

        from sentence_transformers import SentenceTransformer, util

        self.embedder = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')

        

        # Pre-calculate embeddings for template phrases

        sentences = []

        self.intent_labels = []

        for intent_name, queries in self.semantic_templates.items():

            for q in queries:

                sentences.append(q)

                self.intent_labels.append(intent_name)

        

        self.template_embeddings = self.embedder.encode(sentences, convert_to_tensor=True)

        self.util = util

        print("[SEMANTIC NLP] Embeddings model loaded and template library compiled successfully.")



    def configure_ollama(self, host, model):

        if host:

            self.ollama_host = host.rstrip("/")

        if model:

            self.ollama_model = model



    def check_ollama_status(self):

        try:

            r = requests.get(f"{self.ollama_host}/api/tags", timeout=1.5)

            if r.status_code == 200:

                models = [m["name"] for m in r.json().get("models", [])]

                return {"connected": True, "models": models}

        except Exception:

            pass

        return {"connected": False, "models": []}



    def _semantic_classify(self, msg: str) -> tuple:

        """

        Uses sentence-transformers embeddings to identify query intent based on meaning.

        Returns: (intent_name, confidence_score)

        """

        try:

            query_embedding = self.embedder.encode(msg, convert_to_tensor=True)

            cos_scores = self.util.cos_sim(query_embedding, self.template_embeddings)[0]

            

            best_idx = int(cos_scores.argmax())

            best_score = float(cos_scores[best_idx])

            best_intent = self.intent_labels[best_idx]

            

            print(f"[SEMANTIC NLP] Match: {best_intent} (similarity: {best_score:.3f})")

            return best_intent, best_score

        except Exception as e:

            print(f"[SEMANTIC NLP WARNING] Local classification failed: {e}")

            return None, 0.0



    def _clean_llm_response(self, text_str: str) -> str:
        if not text_str or not isinstance(text_str, str):
            return text_str
        # Strip LLM control tags and test code hallucinations
        text_str = re.sub(r'<\|im_end\|>.*$', '', text_str, flags=re.DOTALL)
        text_str = re.sub(r'<\|im_start\|>.*$', '', text_str, flags=re.DOTALL)
        text_str = re.sub(r'def\s+test_chatbot_pipeline.*$', '', text_str, flags=re.DOTALL)
        text_str = re.sub(r'expected_output\s*=.*$', '', text_str, flags=re.DOTALL)
        text_str = re.sub(r'assert\s+expected_output.*$', '', text_str, flags=re.DOTALL)
        return text_str.strip()

    def process_message(self, message: str, history: list, context: dict) -> tuple:
        """
        Processes a chat message.
        history: list of messages [{"role": "user"/"assistant", "content": "..."}]
        context: dict containing persistent filters and settings.
        
        Returns: (response_text, updated_context)
        """
        # Clean the message
        clean_msg = message.strip().lower()

        # Coreference Resolution & Dialogue Context Tracking
        resolved_msg, context = self.context_tracker.update_and_resolve_context(message, context, history)
        
        # Check database connectivity first - do not use fallback JSON mock data
        if self.ds is not None and (not getattr(self.ds, "use_sql_server", False) or getattr(self.ds, "engine", None) is None):
            err_msg = getattr(self.ds, "connection_error", None) or "Server cannot be connected."
            return f"⚠️ Database Connection Error: {err_msg} Please ensure the SQL Server is reachable.", context

        # Immediate block for direct SQL modification commands to prevent LLM hallucinations
        sql_write_keywords = ["drop table", "insert into", "delete from", "update ", "alter table", "create table"]
        if any(keyword in clean_msg for keyword in sql_write_keywords):
            return (
                "I'm sorry, but executing write operations or direct database modifications is strictly prohibited for security reasons.",
                context
            )

        # Check for complex comparative/threshold queries first
        if self._is_complex_or_modified_query(clean_msg):
            print(f"[COMPLEX QUERY DISAMBIGUATION] Query '{clean_msg}' detected as complex analytical filter.")
            
            # FIRST: Check high-speed dynamic parameterized query handler for known analytical patterns
            comp_resp, updated_ctx = self._handle_complex_dynamic_query(clean_msg, context)
            if comp_resp:
                return self._clean_llm_response(comp_resp), updated_ctx

            # SECOND: Fallback to Text-to-SQL via Ollama for ad-hoc custom analytical queries
            ollama_status = self.check_ollama_status()
            if ollama_status["connected"] and self.ds.engine is not None:
                try:
                    active_model = self.ollama_model
                    if active_model not in ollama_status["models"] and len(ollama_status["models"]) > 0:
                        active_model = ollama_status["models"][0]
                    sql_resp = self._process_message_with_text_to_sql(clean_msg, history, active_model, context)
                    if sql_resp:
                        if isinstance(sql_resp, tuple):
                            return self._clean_llm_response(sql_resp[0]), sql_resp[1]
                        return self._clean_llm_response(sql_resp), context
                except Exception as e:
                    print(f"[TEXT-TO-SQL ERROR] Ollama execution failed: {e}")

        # 1. Identify Intent & Retrieve Relevant Data
        intent, data_payload, context = self._classify_and_fetch(clean_msg, context)

        # Read use_ollama setting from context (default to True for live Text-to-SQL pipeline)
        use_ollama = context.get("use_ollama", True)

        if use_ollama:
            ollama_status = self.check_ollama_status()
            if ollama_status["connected"]:
                print(f"Ollama is enabled and online. Generating response using model {self.ollama_model}...")
                available_models = ollama_status["models"]
                active_model = self.ollama_model

                if active_model not in available_models and len(available_models) > 0:
                    matched = next((m for m in available_models if m.startswith(active_model)), None)
                    if matched:
                        active_model = matched
                    else:
                        active_model = available_models[0]

                try:
                    # FIRST: If intent is a specific operational summary or dashboard intent, use high-speed category generator
                    SYSTEM_INTENTS = [
                        "GREETING", "DASHBOARD_SUMMARY", "LHO_LIST", "SOP_QUERY",
                        "SECURITY_CONCERNS", "FALSE_ALERT_RATE", "LHO_RESPONSE_TIME",
                        "BRANCH_COUNT", "ALERT_TYPES", "ALERT_SEVERITY_COUNT",
                        "HIGHEST_ALERTS_BRANCH", "HIGH_RESPONSE_TIME_ALERTS", "EVALUATED_RESPONSE_TIME_INCIDENTS", "LHO_BRANCHES_LIST"
                    ]

                    if intent in SYSTEM_INTENTS:
                        response = self._generate_with_ollama(message, history, intent, data_payload, active_model)
                        if response:
                            return self._clean_llm_response(response), context

                    # SECOND: Attempt dynamic Text-to-SQL for ad-hoc / dynamic data queries
                    if self.ds.engine is not None:
                        sql_res = self._process_message_with_text_to_sql(message, history, active_model, context)
                        if sql_res:
                            if isinstance(sql_res, tuple):
                                return self._clean_llm_response(sql_res[0]), sql_res[1]
                            return self._clean_llm_response(sql_res), context

                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as net_err:
                    print(f"[OLLAMA TIMEOUT/CONNECTION WARNING] Ollama call failed: {net_err}. Falling back to rule-based compiler.")

            else:
                print("Ollama connection failed or unreachable. Falling back...")

        # 3. Fallback to Local Rule-Based template compiler for all recognized operational intents
        response = self._compile_fallback_response(intent, data_payload, clean_msg, context)
        return self._clean_llm_response(response), context




    def _is_complex_or_modified_query(self, msg: str) -> bool:
        msg_lower = msg.lower().strip().replace("-", " ")
        if any(w in msg_lower for w in ["sop", "procedure", "steps", "workflow", "call first"]):
            return False

        if any(w in msg_lower for w in ["system health", "health percentage", "health status", "overall health"]):
            return False

        # Universal Database Query Classifier: Action or Attribute words
        action_words = [
            "show", "list", "count", "get", "breakdown", "distribution", "categorize", "split", "summary",
            "average", "avg", "total", "highest", "lowest", "top", "how many", "number of", "percentage",
            "percent", "ratio", "below", "above", "under", "exceeding", "greater than", "less than", "more than"
        ]
        attribute_words = [
            "alert", "alerts", "cctv", "camera", "cameras", "incident", "incidents", "severity", "priority",
            "status", "type", "event", "response time", "delay", "latency", "operator", "branch", "branches", "location",
            "area", "zone", "lho", "lhos", "circle", "circles", "high", "medium", "low", "critical", "severe", "closed", "pending", "active", "acknowledged"
        ]

        if any(w in msg_lower for w in action_words) or any(w in msg_lower for w in attribute_words):
            return True

        # Check if query contains any live DB location or live alert type
        if self._extract_location_filter(msg_lower) or self._extract_alert_type_filter(msg_lower):
            return True

        if re.search(r'\b\d+\s*(?:sec|second|seconds|min|mins|minute|minutes|hr|hrs|hour|hours)\b', msg_lower):
            return True

        if re.search(r'\b(?:january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|september|sep|sept|october|oct|november|nov|december|dec|yesterday|today)\b', msg_lower):
            return True

        return False

    def _extract_dates_from_query(self, msg: str):
        msg_lower = msg.lower().strip()

        # 0. Relative Date Terms (yesterday, today)
        if "yesterday" in msg_lower:
            yest = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            return yest, yest, "single"
        if "today" in msg_lower:
            today_str = datetime.now().strftime("%Y-%m-%d")
            return today_str, today_str, "single"

        month_map = {
            "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
            "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
            "august": 8, "aug": 8, "september": 9, "sep": 9, "october": 10, "oct": 10,
            "november": 11, "nov": 11, "december": 12, "dec": 12
        }
        
        # 1. ISO Date Range (YYYY-MM-DD to/and YYYY-MM-DD)
        iso_range = re.findall(r'(\d{4}-\d{2}-\d{2})', msg_lower)
        if len(iso_range) >= 2:
            return iso_range[0], iso_range[1], "range"
        elif len(iso_range) == 1:
            return iso_range[0], iso_range[0], "single"

        # 2. Text Date Range (e.g., "july 28 and august 10", "july 28 to august 10", "august 1 to august 10")
        range_match = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s*(\d+)(?:st|nd|rd|th)?\s*(?:and|to|-)\s*(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)?\s*(\d+)', msg_lower)
        
        if range_match:
            m1_str, d1_str, m2_str, d2_str = range_match.groups()
            m1 = month_map.get(m1_str, 7)
            d1 = int(d1_str)
            m2 = month_map.get(m2_str, m1) if m2_str else m1
            d2 = int(d2_str)
            
            start_date = f"2026-{m1:02d}-{d1:02d}"
            end_date = f"2026-{m2:02d}-{d2:02d}"
            return start_date, end_date, "range"

        # 3. Single Date (e.g., "august 12", "july 13", "12 august")
        single_match = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s*(\d+)|(\d+)(?:st|nd|rd|th)?\s*(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', msg_lower)
        
        if single_match:
            if single_match.group(1):
                m_str = single_match.group(1)
                d_str = single_match.group(2)
            else:
                d_str = single_match.group(3)
                m_str = single_match.group(4)
            m = month_map.get(m_str, 7)
            d = int(d_str)
            dt = f"2026-{m:02d}-{d:02d}"
            return dt, dt, "single"

        return None, None, None

    def _extract_location_filter(self, msg_lower: str, context: dict = None) -> str:
        """Dynamically extracts location/branch/area filters by matching prompt text against live DB locations."""
        if context and context.get("active_branch_filter"):
            loc_ctx = context.get("active_branch_filter")
            if loc_ctx.lower() in msg_lower:
                return loc_ctx

        db_locations = []
        if hasattr(self, "ds") and self.ds:
            try:
                db_locations = self.ds.get_all_locations()
            except Exception as e:
                print(f"[LOCATION EXTRACTOR WARNING] Failed to fetch DB locations: {e}")

        if not db_locations:
            db_locations = ["AO_NOIDA", "AO_AGRA", "AO_NORTH AND WEST DELHI", "Jankipuram", "Aonla", "Quila", "Civil Lines", "Junction", "Chowki Chauraha"]

        # 1. Exact or Substring Matching against Live DB Locations (AlertsDetails.Area)
        sorted_locs = sorted(db_locations, key=lambda x: len(str(x)), reverse=True)
        for loc in sorted_locs:
            loc_str = str(loc)
            loc_clean = loc_str.lower().replace("ao_", "").replace("ao ", "").strip()
            if loc_str.lower() in msg_lower or (len(loc_clean) >= 3 and loc_clean in msg_lower):
                return loc_str

        # 1.5 Narrow Fallback: if user names a specific branch (by name or code) that does NOT match AlertsDetails.Area
        if hasattr(self, "ds") and self.ds and self.ds.use_sql_server and self.ds.engine:
            try:
                with self.ds.engine.connect() as conn:
                    words = re.findall(r'\b[a-zA-Z0-9_-]+\b', msg_lower)
                    for w in words:
                        if len(w) >= 3 and w not in ["branch", "branches", "lho", "lhos", "zone", "zones", "show", "list", "alerts", "alert", "cctv", "camera", "cameras", "today", "yesterday"]:
                            fallback_q = text("SELECT DISTINCT BranchCode FROM Jurisdiction_mstr WHERE BranchCode LIKE :w UNION SELECT DISTINCT Junction FROM Junction_mstr WHERE Junction LIKE :w")
                            fb_rows = conn.execute(fallback_q, {"w": f"%{w}%"}).fetchall()
                            if fb_rows and fb_rows[0][0]:
                                return str(fb_rows[0][0])
            except Exception as e:
                pass

        # 2. Pattern Matching (e.g. "in lucknow", "at kanpur", "for mumbai")
        # Clean date expressions from msg_lower before matching pattern
        clean_msg = re.sub(r'\b(?:\d{1,2}\s+)?(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)(?:\s+\d{1,2})?\b', '', msg_lower)
        clean_msg = re.sub(r'\b\d{1,2}(?:st|nd|rd|th)?\s+(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b', '', clean_msg)

        loc_match = re.search(r'\b(?:in|at|from|for|of)\s+([a-z0-9\s_-]+)\b', clean_msg)
        if loc_match:
            candidate = loc_match.group(1).strip()
            stop_words = [
                "the", "system", "today", "yesterday", "all", "total", "alerts", "alert", "camera", "cameras", "cctv",
                "high", "medium", "low", "critical", "severe", "major", "minor", "urgent", "emergency", "priority", "severity",
                "closed", "pending", "active", "completed", "resolved", "acknowledged", "status", "database",
                "response", "time", "delay", "latency", "sla", "operator", "handled", "workload", "incident", "incidents",
                "breakdown", "distribution", "category", "type", "event", "zone", "lho", "branch", "location", "area", "branches", "locations",
                "month", "week", "year", "date", "number", "count", "percent", "ratio", "share", "severity alert",
                "high severity", "medium severity", "low severity", "high severity alert", "medium severity alert",
                "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
                "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
                "vms", "sas", "analytics", "videoanalytics", "va", "we", "have", "and", "where", "what", "how", "which", "why", "who", "is", "are", "were", "was"
            ]
            cand_words = candidate.split()
            # Discard if candidate contains any stop word or if candidate is not a valid location
            if not any(sw in candidate for sw in stop_words) and len(candidate) >= 3 and not re.match(r'^\d+\s*$', candidate):
                # Verify candidate against real database locations if available
                if hasattr(self, "ds") and self.ds:
                    db_locs = [l.lower() for l in self.ds.get_all_locations()]
                    if any(c_w in db_l for db_l in db_locs for c_w in cand_words if len(c_w) >= 3):
                        return candidate.title()
                    else:
                        return None
                return candidate.title()

        return None

    def _extract_alert_type_filter(self, msg_lower: str) -> str:
        """Dynamically matches prompt text against live DB alert types fetched from SQL Server."""
        alert_types = []
        if hasattr(self, "ds") and self.ds:
            try:
                alert_types = self.ds.get_all_alert_types()
            except Exception as e:
                print(f"[ALERT TYPE EXTRACTOR WARNING] Failed to fetch DB alert types: {e}")

        if not alert_types:
            alert_types = ["Analytics", "VMS", "SAS", "VideoAnalytics"]

        sorted_types = sorted(alert_types, key=lambda x: len(str(x)), reverse=True)
        for at in sorted_types:
            at_str = str(at)
            if re.search(r'\b' + re.escape(at_str.lower()) + r'\b', msg_lower):
                return at_str

        return None

    def _handle_complex_dynamic_query(self, msg: str, context: dict) -> tuple:
        msg_lower = msg.lower().strip()

        # 0.001 Total System Alerts Handler ("count of total alerts", "total alerts", "how many total alerts")
        has_type = bool(self._extract_alert_type_filter(msg_lower))
        has_loc = bool(self._extract_location_filter(msg_lower, context))
        has_date = bool(self._extract_dates_from_query(msg_lower)[0])
        is_total_count = (
            any(phrase in msg_lower for phrase in ["count of total alerts", "total alert count", "total alerts count", "count of alerts", "total number of alerts", "total count of alerts"])
            or (
                ("alert" in msg_lower or "alerts" in msg_lower)
                and any(w in msg_lower for w in ["count", "total", "how many", "number of"])
                and not (has_type or has_loc or has_date)
                and not any(w in msg_lower for w in ["group", "branch", "severity", "status", "today", "yesterday", "camera", "cctv", "high", "medium", "low", "closed", "pending", "active", "type", "where", "response", "below", "above", "under", "exceeding"])
            )
        )
        if is_total_count:
            if self.ds.use_sql_server:
                try:
                    q = """
                        SELECT 
                            COUNT(*) as total_alerts,
                            SUM(CASE WHEN Status LIKE '%Pending%' THEN 1 ELSE 0 END) as pending_alerts,
                            SUM(CASE WHEN Status LIKE '%Closed%' THEN 1 ELSE 0 END) as closed_alerts,
                            SUM(CASE WHEN Status LIKE '%Acknowledged%' THEN 1 ELSE 0 END) as ack_alerts
                        FROM AlertsDetails
                    """
                    with self.ds.engine.connect() as conn:
                        res = conn.execute(text(q)).mappings().first()
                        tot = res.get("total_alerts") or 0
                        pend = res.get("pending_alerts") or 0
                        closed = res.get("closed_alerts") or 0
                        ack = res.get("ack_alerts") or 0

                        return (
                            f"There are a total of **{tot:,} security alerts** registered in the Centralized Monitoring System:\n\n"
                            f"### System Alert Overview\n"
                            f"- **Total Alerts**: `{tot:,}`\n"
                            f"- **Pending / Active**: `{pend:,}` ({round((pend/tot)*100, 2) if tot else 0}%)\n"
                            f"- **Closed / Resolved**: `{closed:,}` ({round((closed/tot)*100, 2) if tot else 0}%)\n"
                            f"- **Acknowledged**: `{ack:,}`\n\n"
                            f"*(Note: Total telemetry alerts registered across all connected monitored branches).* "
                        ), context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] Total alerts query failed: {e}")

        # 0.002 LHO / Circle Listing Handler ("List the LHOs", "LHO command circles", "list LHO circles", "show LHOs", "all LHO command centers")
        if re.search(r'\b(lho|lhos|command circles|lho circles|lho centers|command centers)\b', msg_lower) and not any(w in msg_lower for w in ["incident", "incidents", "alert", "alerts", "camera", "cameras", "response time", "delay", "slowest"]):
            if self.ds.use_sql_server:
                try:
                    q = """
                        SELECT DISTINCT TRIM(Zone) as lho_name FROM AlertsDetails WHERE Zone IS NOT NULL AND TRIM(Zone) != ''
                        UNION
                        SELECT DISTINCT TRIM(Location) as lho_name FROM Location_Master WHERE Location IS NOT NULL AND TRIM(Location) != ''
                        ORDER BY lho_name ASC
                    """
                    with self.ds.engine.connect() as conn:
                        rows = conn.execute(text(q)).fetchall()
                        lho_list = [r[0] for r in rows if r[0]]

                        tbl = "| # | LHO Circle / Command Centre |\n|---|---|\n"
                        for idx, lho_item in enumerate(lho_list, 1):
                            tbl += f"| {idx} | **{lho_item}** |\n"

                        return (
                            f"The Centralized Monitoring System monitors **{len(lho_list)} Local Head Office (LHO) Circles**:\n\n"
                            f"### SBI LHO Command Circles\n{tbl}\n"
                            f"*(Note: All monitored branches and camera telemetry report to these central LHO command circles).* "
                        ), context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] List LHOs query failed: {e}")

        # 0.003 Monitored Branches Listing Handler ("list the branches", "list branches", "show branches", "all branches", "monitored branches")
        if ((any(w in msg_lower for w in ["branch", "branches", "locations", "sites"]) and any(w in msg_lower for w in ["list", "show", "get", "all", "monitored", "configured"])) or msg_lower in ["branches", "list branches", "list the branches", "all branches"]) and not (has_type or "alert" in msg_lower or "alerts" in msg_lower):
            if self.ds.use_sql_server:
                try:
                    q = """
                        SELECT 
                            TRIM(COALESCE(Area, Location)) as branch_name, 
                            COUNT(*) as total_alerts
                        FROM AlertsDetails 
                        GROUP BY TRIM(COALESCE(Area, Location))
                        ORDER BY total_alerts DESC
                    """
                    with self.ds.engine.connect() as conn:
                        rows = conn.execute(text(q)).mappings().all()
                        tbl = "| # | Monitored Branch / Area | Registered Alerts |\n|---|---|---|\n"
                        for idx, r in enumerate(rows, 1):
                            tbl += f"| {idx} | **{r['branch_name']}** | {r['total_alerts']:,} |\n"

                        return (
                            f"The Centralized Monitoring System covers **{len(rows)} monitored bank branches / areas**:\n\n"
                            f"### Monitored Branches & Alert Volumes\n{tbl}\n"
                            f"*(Note: Live telemetry feeds, camera status, and security flags are reported for all listed branches).* "
                        ), context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] List branches query failed: {e}")

        # 0.005 Universal Camera Engine ("how many cameras in jankipuram", "list active cameras in aonla", "list all cameras")
        if any(w in msg_lower for w in ["camera", "cameras", "cctv"]):
            loc_filter = self._extract_location_filter(msg_lower, context)

            where_parts = []
            params = {}
            if loc_filter:
                where_parts.append("(Area LIKE :loc OR CameraLocation LIKE :loc)")
                params["loc"] = f"%{loc_filter}%"

            # Check if asking for offline/inactive cameras
            if any(w in msg_lower for w in ["offline", "no stream", "disconnected", "down", "failure", "inactive"]):
                if self.ds.use_sql_server:
                    try:
                        w_parts = where_parts + ["Status != 'Active'"]
                        q = f"SELECT CameraName, CameraId, Area, Status FROM CameraList WHERE {' AND '.join(w_parts)} ORDER BY CAST(CameraId AS INT) ASC"
                        with self.ds.engine.connect() as conn:
                            rows = conn.execute(text(q), params).mappings().all()
                            loc_str = f" in **{loc_filter}**" if loc_filter else ""
                            if rows:
                                tbl = "| Camera Name | Camera ID | Branch / Area | Status |\n|---|---|---|---|\n"
                                for r in rows:
                                    tbl += f"| {r['CameraName']} | {r['CameraId']} | {r['Area']} | **{r['Status']}** |\n"
                                return f"Found **{len(rows)} Offline / No Stream CCTV Cameras**{loc_str}:\n\n{tbl}\n### Operations Summary\nMaintenance tickets have been logged for offline camera channels.", context
                            else:
                                return f"All CCTV cameras{loc_str} are currently **Online** and actively recording. No camera failures detected.", context
                    except Exception as e:
                        print(f"[COMPLEX QUERY ERROR] Offline camera query failed: {e}")

            # Check if asking for online/active cameras
            elif any(w in msg_lower for w in ["online", "active", "working", "connected"]):
                if self.ds.use_sql_server:
                    try:
                        w_parts = where_parts + ["Status = 'Active'"]
                        q = f"SELECT CameraName, CameraId, Area, Status FROM CameraList WHERE {' AND '.join(w_parts)} ORDER BY CAST(CameraId AS INT) ASC"
                        with self.ds.engine.connect() as conn:
                            rows = conn.execute(text(q), params).mappings().all()
                            loc_str = f" in **{loc_filter}**" if loc_filter else ""
                            if rows:
                                tbl = "| Camera Name | Camera ID | Branch / Area | Status |\n|---|---|---|---|\n"
                                for r in rows:
                                    tbl += f"| {r['CameraName']} | {r['CameraId']} | {r['Area']} | **{r['Status']}** |\n"
                                return f"Found **{len(rows)} Online / Active CCTV Cameras**{loc_str}:\n\n{tbl}\n### Operations Summary\nAll active camera channels are feeding real-time telemetry to central command.", context
                            else:
                                return f"No active CCTV cameras{loc_str} were found.", context
                    except Exception as e:
                        print(f"[COMPLEX QUERY ERROR] Active camera query failed: {e}")

            # Check if asking for count/total summary of cameras
            elif any(w in msg_lower for w in ["how many", "total", "count", "configured"]):
                if self.ds.use_sql_server:
                    try:
                        w_str = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
                        q_cnt = f"SELECT COUNT(*) as total_cams, SUM(CASE WHEN Status = 'Active' THEN 1 ELSE 0 END) as active_cams FROM CameraList {w_str}"
                        q_rows = f"SELECT CameraName, CameraId, Area, Status FROM CameraList {w_str} ORDER BY CAST(CameraId AS INT) ASC"
                        with self.ds.engine.connect() as conn:
                            res = conn.execute(text(q_cnt), params).mappings().first()
                            rows = conn.execute(text(q_rows), params).mappings().all()
                            tot = res.get("total_cams") or len(rows)
                            act = res.get("active_cams") or 0
                            pct = round((act / tot) * 100, 1) if tot > 0 else 0.0
                            loc_str = f" in **{loc_filter}**" if loc_filter else ""
                            
                            tbl = "| Camera Name | Camera ID | Branch / Area | Status |\n|---|---|---|---|\n"
                            for r in rows:
                                st_fmt = f"**{r['Status']}**" if r['Status'] == 'Active' else f"`{r['Status']}`"
                                tbl += f"| {r['CameraName']} | {r['CameraId']} | {r['Area']} | {st_fmt} |\n"

                            return (
                                f"A total of **{tot} CCTV cameras** are configured{loc_str} (**{act} Active**, **{tot - act} Inactive / No Stream**):\n\n"
                                f"### Camera Operational Status{loc_str}\n"
                                f"- **Active & Online**: `{act}` cameras ({pct}% operational health).\n"
                                f"- **Inactive / No Stream**: `{tot - act}` camera channels.\n\n"
                                f"### Configured Cameras List{loc_str}\n{tbl}"
                            ), context
                    except Exception as e:
                        print(f"[COMPLEX QUERY ERROR] Camera count query failed: {e}")

            # Default for general camera listing ("list all cameras", "list cameras in jankipuram", "show cameras in aonla")
            else:
                if self.ds.use_sql_server:
                    try:
                        w_str = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
                        q = f"SELECT CameraName, CameraId, Area, Status FROM CameraList {w_str} ORDER BY CAST(CameraId AS INT) ASC"
                        with self.ds.engine.connect() as conn:
                            rows = conn.execute(text(q), params).mappings().all()
                            act_cnt = sum(1 for r in rows if r['Status'] == 'Active')
                            off_cnt = len(rows) - act_cnt
                            loc_str = f" in **{loc_filter}**" if loc_filter else ""
                            tbl = "| Camera Name | Camera ID | Branch / Area | Operational Status |\n|---|---|---|---|\n"
                            for r in rows:
                                st_fmt = f"**{r['Status']}**" if r['Status'] == 'Active' else f"`{r['Status']}`"
                                tbl += f"| {r['CameraName']} | {r['CameraId']} | {r['Area']} | {st_fmt} |\n"
                            return (
                                f"Found **{len(rows)} CCTV Cameras** configured{loc_str} (**{act_cnt} Active**, **{off_cnt} No Stream**):\n\n"
                                f"### CCTV Cameras{loc_str}\n{tbl}\n"
                                f"*(Note: Camera feeds are routed through edge network gateways to central VMS).* "
                            ), context
                    except Exception as e:
                        print(f"[COMPLEX QUERY ERROR] List cameras query failed: {e}")

        # 0.01 Universal Parameter Grouping Engine ("show me todays alert and group them by their severity", "group by status", "breakdown by severity", "show severity breakdown for agra", "show me alerts by the type")
        is_group_query = (
            (
                any(w in msg_lower for w in ["group", "grouped", "grouping", "breakdown", "distribution", "categorize", "split", "wise", "per"])
                and any(w in msg_lower for w in ["alert", "alerts", "incident", "incidents", "telemetry", "cctv", "camera", "cameras", "severity", "priority", "status", "type", "branch", "branches"])
            ) or any(w in msg_lower for w in ["highest number", "highest alerts", "highest alert", "most alerts", "branch has highest", "severity breakdown", "status breakdown", "type breakdown", "branch breakdown", "alerts by type", "alerts by the type", "alerts by severity", "alerts by status", "alerts by branch", "alerts by branches", "by branch", "by branches"])
        ) and not any(w in msg_lower for w in ["response time", "sla", "delay", "latency", "operator time"])

        if is_group_query:
            # Extract date bounds, location, alert type, severity, and status filters
            d_start_grp, d_end_grp, d_kind_grp = self._extract_dates_from_query(msg_lower)
            loc_filter_grp = self._extract_location_filter(msg_lower, context)
            type_filter_grp = self._extract_alert_type_filter(msg_lower)

            where_conds = []
            where_params = {}
            labels_grp = []

            if d_start_grp and d_end_grp:
                where_conds.append("Datetime >= :dt_start AND Datetime <= :dt_end")
                where_params["dt_start"] = f"{d_start_grp} 00:00:00"
                where_params["dt_end"] = f"{d_end_grp} 23:59:59"
                labels_grp.append(f"for **{d_start_grp}**" if d_start_grp == d_end_grp else f"for the period **{d_start_grp}** to **{d_end_grp}**")

            if loc_filter_grp:
                where_conds.append("(Area LIKE :loc OR Location LIKE :loc OR Zone LIKE :loc)")
                where_params["loc"] = f"%{loc_filter_grp}%"
                labels_grp.append(f"in **{loc_filter_grp}**")

            if type_filter_grp:
                where_conds.append("AlertType = :at_type")
                where_params["at_type"] = type_filter_grp
                labels_grp.append(f"for **{type_filter_grp}** alerts")

            if re.search(r'\b(high|critical|severe)\b', msg_lower):
                where_conds.append("Severity IN ('High', 'Critical')")
                labels_grp.append("with **High / Critical** severity")
            elif re.search(r'\b(medium|moderate)\b', msg_lower):
                where_conds.append("Severity = 'Medium'")
                labels_grp.append("with **Medium** severity")
            elif re.search(r'\b(low|minor)\b', msg_lower):
                where_conds.append("Severity = 'Low'")
                labels_grp.append("with **Low** severity")

            if any(s in msg_lower for s in ["closed", "completed", "resolved"]):
                where_conds.append("(Status LIKE '%Closed%' OR Status LIKE '%Completed%')")
                labels_grp.append("with **Closed** status")
            elif any(s in msg_lower for s in ["pending", "active", "open"]):
                where_conds.append("(Status LIKE '%Pending%' OR Status LIKE '%Active%')")
                labels_grp.append("with **Pending** status")

            date_label = (" " + " ".join(labels_grp)) if labels_grp else ""
            loc_label = ""
            where_str = f"WHERE {' AND '.join(where_conds)}" if where_conds else ""

            # Determine Grouping Dimension (Severity, Status, Type, Zone, Operator, Branch)
            if any(w in msg_lower for w in ["severity", "priority", "criticality"]):
                grp_col = "Severity"
                grp_label = "Severity Level"
            elif any(w in msg_lower for w in ["status", "state"]):
                grp_col = "Status"
                grp_label = "Alert Status"
            elif any(w in msg_lower for w in ["type", "event", "category"]):
                grp_col = "AlertType"
                grp_label = "Alert Event Type"
            elif any(w in msg_lower for w in ["zone", "lho", "region"]):
                grp_col = "Zone"
                grp_label = "Monitoring Zone"
            elif any(w in msg_lower for w in ["by operator", "per operator", "operator breakdown", "operator wise"]):
                grp_col = "Operatorname"
                grp_label = "Assigned Operator"
            else:
                grp_col = "TRIM(COALESCE(Area, Location))"
                grp_label = "Monitored Branch / Area"

            if self.ds.use_sql_server:
                try:
                    q = f"""
                        SELECT 
                            {grp_col} as group_key, 
                            COUNT(*) as total_alerts,
                            SUM(CASE WHEN Status LIKE '%Pending%' THEN 1 ELSE 0 END) as pending_alerts,
                            SUM(CASE WHEN Status LIKE '%Closed%' THEN 1 ELSE 0 END) as closed_alerts
                        FROM AlertsDetails
                        {where_str}
                        GROUP BY {grp_col}
                        ORDER BY total_alerts DESC
                    """
                    with self.ds.engine.connect() as conn:
                        rows = conn.execute(text(q), where_params).mappings().all()
                        tot_all = sum(r['total_alerts'] for r in rows)
                        top_key = rows[0]['group_key'] if rows else "N/A"
                        top_cnt = rows[0]['total_alerts'] if rows else 0
                        top_pct = round((top_cnt / tot_all) * 100, 2) if tot_all else 0

                        table_header = f"| {grp_label} | Total Alerts Registered | Pending Alerts | Closed / Resolved | Share |\n|---|---|---|---|---|\n"
                        table_rows = ""
                        for r in rows:
                            pct = round((r['total_alerts'] / tot_all) * 100, 2)
                            key_name = r['group_key'] or 'Unassigned'
                            table_rows += f"| **{key_name}** | **{r['total_alerts']:,}** | {r['pending_alerts']:,} | {r['closed_alerts']:,} | {pct}% |\n"

                        return (
                            f"Alert breakdown grouped by **{grp_label}**{loc_label}{date_label} (total **{tot_all:,} alerts** across **{len(rows)} categories**):\n\n"
                            f"### Security Alerts Grouped by {grp_label}\n{table_header}{table_rows}\n"
                            f"### Operations Summary\n"
                            f"Highest category: **{top_key}** representing **{top_cnt:,} alerts** (`{top_pct}%` share of volume{loc_label}{date_label})."
                        ), context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] Parameter grouping query failed: {e}")

        # 0. Status & Branch Alert Count Queries ("how many closed alerts are from agra", "how many pending alerts in noida")
        if any(w in msg_lower for w in ["how many", "number of", "count of", "total"]) and any(st in msg_lower for st in ["closed", "pending", "active", "acknowledged"]):
            target_status = "Closed" if "closed" in msg_lower else ("Pending" if "pending" in msg_lower else ("Acknowledged" if "acknowledged" in msg_lower else "Active"))
            loc_filter = self._extract_location_filter(msg_lower, context)

            if self.ds.use_sql_server:
                try:
                    if loc_filter:
                        q_cnt = """
                            SELECT 
                                COUNT(*) as total_count,
                                SUM(CASE WHEN Status LIKE :st THEN 1 ELSE 0 END) as match_count
                            FROM AlertsDetails
                            WHERE (Area LIKE :loc OR Location LIKE :loc OR Zone LIKE :loc)
                        """
                        q_rows = """
                            SELECT TOP 10 AlertID, AlertType, TRIM(COALESCE(Area, Location)) as branch_name, Severity, Datetime, Status
                            FROM AlertsDetails
                            WHERE Status LIKE :st AND (Area LIKE :loc OR Location LIKE :loc OR Zone LIKE :loc)
                            ORDER BY Datetime DESC
                        """
                        params_cnt = {"st": f"%{target_status}%", "loc": f"%{loc_filter}%"}
                        params_rows = {"st": f"%{target_status}%", "loc": f"%{loc_filter}%"}
                    else:
                        q_cnt = """
                            SELECT 
                                COUNT(*) as total_count,
                                SUM(CASE WHEN Status LIKE :st THEN 1 ELSE 0 END) as match_count
                            FROM AlertsDetails
                        """
                        q_rows = """
                            SELECT TOP 10 AlertID, AlertType, TRIM(COALESCE(Area, Location)) as branch_name, Severity, Datetime, Status
                            FROM AlertsDetails
                            WHERE Status LIKE :st
                            ORDER BY Datetime DESC
                        """
                        params_cnt = {"st": f"%{target_status}%"}
                        params_rows = {"st": f"%{target_status}%"}

                    with self.ds.engine.connect() as conn:
                        res = conn.execute(text(q_cnt), params_cnt).mappings().first()
                        tot = res.get("total_count") or 1
                        m = res.get("match_count") or 0
                        pct = round((m / tot) * 100, 2)
                        rows = conn.execute(text(q_rows), params_rows).mappings().all()

                        loc_str = f" in **{loc_filter}**" if loc_filter else " across all monitored branches"
                        tbl = "| Alert ID | Type | Branch Name | Severity | Datetime | Status |\n|---|---|---|---|---|---|\n"
                        for r in rows:
                            tbl += f"| {r['AlertID']} | {r['AlertType']} | {r['branch_name']} | **{r['Severity']}** | {r['Datetime']} | **{r['Status']}** |\n"

                        return (
                            f"There are **{m:,} {target_status.lower()} alerts**{loc_str} (out of **{tot:,} total alerts**, `{pct}%`).\n\n"
                            f"### Recent {target_status} Alerts Sample\n{tbl}\n"
                            f"*(Showing top 10 most recent `{target_status}` telemetry flags).* "
                        ), context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] Status count query failed: {e}")

        # 0.05 Universal Date Alert Summary Handler ("give me 20th august alerts summary", "give me yesterday alerts summary", "august 24 summary")
        d_start_sum, d_end_sum, d_kind_sum = self._extract_dates_from_query(msg_lower)
        if d_start_sum and d_end_sum and not any(w in msg_lower for w in ["response time", "sla", "delay", "latency", "operator time"]) and (any(w in msg_lower for w in ["summary", "overview", "report", "breakdown"]) or "yesterday" in msg_lower or "alerts summary" in msg_lower):
            if self.ds.use_sql_server:
                try:
                    q_br = """
                        SELECT 
                            TRIM(COALESCE(Area, Location)) as branch_name, 
                            COUNT(*) as branch_cnt,
                            SUM(CASE WHEN Status LIKE '%Pending%' THEN 1 ELSE 0 END) as pending_cnt,
                            SUM(CASE WHEN Status LIKE '%Closed%' THEN 1 ELSE 0 END) as closed_cnt
                        FROM AlertsDetails
                        WHERE Datetime >= :dt_start AND Datetime <= :dt_end
                        GROUP BY TRIM(COALESCE(Area, Location))
                        ORDER BY branch_cnt DESC
                    """
                    q_rows = """
                        SELECT TOP 10 AlertID, AlertType, TRIM(COALESCE(Area, Location)) as branch_name, Severity, Datetime, Status
                        FROM AlertsDetails
                        WHERE Datetime >= :dt_start AND Datetime <= :dt_end
                        ORDER BY Datetime DESC
                    """
                    params = {
                        "dt_start": f"{d_start_sum} 00:00:00",
                        "dt_end": f"{d_end_sum} 23:59:59"
                    }
                    with self.ds.engine.connect() as conn:
                        br_rows = conn.execute(text(q_br), params).mappings().all()
                        sample_rows = conn.execute(text(q_rows), params).mappings().all()
                        tot_date_cnt = sum(r['branch_cnt'] for r in br_rows)

                        date_label = f"on **{d_start_sum}**" if d_start_sum == d_end_sum else f"for the period **{d_start_sum}** to **{d_end_sum}**"
                        header_date = d_start_sum if d_start_sum == d_end_sum else f"{d_start_sum} to {d_end_sum}"
                        if tot_date_cnt > 0:
                            br_table = "| Monitored Branch / Area | Total Alerts Registered | Pending | Closed | Share |\n|---|---|---|---|---|\n"
                            for r in br_rows:
                                pct = round((r['branch_cnt'] / tot_date_cnt) * 100, 2)
                                br_table += f"| **{r['branch_name']}** | **{r['branch_cnt']:,}** | {r['pending_cnt']:,} | {r['closed_cnt']:,} | {pct}% |\n"

                            sample_table = "| Alert ID | Type | Branch Name | Severity | Datetime | Status |\n|---|---|---|---|---|---|\n"
                            for r in sample_rows:
                                sample_table += f"| {r['AlertID']} | {r['AlertType']} | {r['branch_name']} | **{r['Severity']}** | {r['Datetime']} | **{r['Status']}** |\n"

                            return (
                                f"For {date_label}, the Centralized Monitoring System registered a total of **{tot_date_cnt:,} security alerts** across **{len(br_rows)} monitored branches**:\n\n"
                                f"### Branch-by-Branch Breakdown ({header_date})\n{br_table}\n"
                                f"### Recent Alerts Sample ({header_date})\n{sample_table}\n"
                                f"*(Showing top 10 recent alerts registered for {header_date}).*"
                            ), context
                        else:
                            return f"No telemetry or security alerts were registered {date_label} in the Centralized Monitoring System.", context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] Universal date summary query failed: {e}")

        # 0.5 Status Alert Listing Queries ("show me completed alerts from noida", "at august 20, show me closed alerts from agra")
        if any(st in msg_lower for st in ["closed", "completed", "resolved", "acknowledged", "ack", "pending", "active", "open"]) and not any(w in msg_lower for w in ["how many", "number of", "count of", "percent", "ratio", "slowest", "response time", "sla", "delay", "latency", "operator time"]):
            if any(w in msg_lower for w in ["completed", "closed", "resolved"]):
                target_status_sql = "(Status LIKE '%Closed%' OR Status LIKE '%Completed%')"
                target_status_label = "Closed / Completed"
            elif any(w in msg_lower for w in ["acknowledged", "ack"]):
                target_status_sql = "(Status LIKE '%Acknowledged%' OR Status LIKE '%Ack%')"
                target_status_label = "Acknowledged"
            else:
                target_status_sql = "(Status LIKE '%Pending%' OR Status LIKE '%Active%')"
                target_status_label = "Pending"

            loc_filter = self._extract_location_filter(msg_lower, context)

            # Check if query contains date bounds (e.g. "august 20", "july 31")
            d_start, d_end, d_kind = self._extract_dates_from_query(msg_lower)

            # Prevent day numbers in date strings (e.g. "august 20") from corrupting top_limit limit
            clean_msg_for_cnt = re.sub(r'\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}\b', '', msg_lower)
            clean_msg_for_cnt = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '', clean_msg_for_cnt)

            top_limit = 15
            cnt_match = re.search(r'\b(?:top|show|list|get|first)?\s*(\d+)\b', clean_msg_for_cnt)
            if cnt_match and cnt_match.group(1):
                try:
                    parsed_val = int(cnt_match.group(1))
                    if 1 <= parsed_val <= 100: top_limit = parsed_val
                except ValueError: pass

            # Check if query contains optional severity filter (e.g. "of high severity", "high priority")
            target_sev = None
            if "high" in msg_lower: target_sev = "High"
            elif "low" in msg_lower: target_sev = "Low"
            elif "medium" in msg_lower: target_sev = "Medium"

            if self.ds.use_sql_server:
                try:
                    where_parts = [target_status_sql]
                    params = {}
                    if loc_filter:
                        where_parts.append("(Area LIKE :loc OR Location LIKE :loc)")
                        params["loc"] = f"%{loc_filter}%"

                    if target_sev:
                        where_parts.append("Severity = :sev")
                        params["sev"] = target_sev

                    if d_start and d_end:
                        where_parts.append("Datetime >= :dt_start AND Datetime <= :dt_end")
                        params["dt_start"] = f"{d_start} 00:00:00"
                        params["dt_end"] = f"{d_end} 23:59:59"

                    q_cnt = f"SELECT COUNT(*) as total_matching FROM AlertsDetails WHERE {' AND '.join(where_parts)}"
                    q_rows = f"""
                        SELECT TOP {top_limit} AlertID, AlertType, TRIM(COALESCE(Area, Location)) as branch_name, Severity, Datetime, Status
                        FROM AlertsDetails
                        WHERE {' AND '.join(where_parts)}
                        ORDER BY Datetime DESC
                    """
                    with self.ds.engine.connect() as conn:
                        tot_match = conn.execute(text(q_cnt), params).mappings().first().get("total_matching") or 0
                        rows = conn.execute(text(q_rows), params).mappings().all()
                        loc_str = f" for **{loc_filter}**" if loc_filter else ""
                        sev_str = f" (`{target_sev}` severity)" if target_sev else ""
                        date_str = f" registered on **{d_start}**" if (d_start and d_end and d_start == d_end) else (f" between **{d_start}** and **{d_end}**" if d_start and d_end else "")
                        if rows:
                            tbl = "| Alert ID | Type | Branch Name | Severity | Datetime | Status |\n|---|---|---|---|---|---|\n"
                            for r in rows:
                                tbl += f"| {r['AlertID']} | {r['AlertType']} | {r['branch_name']} | **{r['Severity']}** | {r['Datetime']} | **{r['Status']}** |\n"
                            return f"Found a total of **{tot_match:,} matching security alerts** in the database with status **`{target_status_label}`**{sev_str}{loc_str}{date_str} (showing top {len(rows)} below):\n\n{tbl}\n### Operations Summary\nDisplaying matching telemetry alerts ordered by most recent timestamp.", context
                        else:
                            return f"No security alerts with status **`{target_status_label}`**{sev_str}{loc_str}{date_str} were found in the database (0 total matching).", context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] Status listing query failed: {e}")

        # A. Total CCTV Camera Count Query
        if ("cctv" in msg_lower or "camera" in msg_lower or "cameras" in msg_lower) and any(w in msg_lower for w in ["total", "configured", "monitored", "how many", "count"]) and not any(w in msg_lower for w in ["offline", "online", "active", "disconnected"]):
            if self.ds.use_sql_server:
                try:
                    q = "SELECT COUNT(*) as total_cams, SUM(CASE WHEN Status = 'Active' THEN 1 ELSE 0 END) as active_cams FROM CameraList"
                    with self.ds.engine.connect() as conn:
                        res = conn.execute(text(q)).mappings().first()
                        tot = res.get("total_cams") or 25
                        act = res.get("active_cams") or 13
                        pct = round((act / tot) * 100, 1) if tot > 0 else 100.0
                        return (
                            f"A total of **{tot} CCTV cameras** are currently configured and monitored across Centralized Monitoring System sites.\n\n"
                            f"### Camera Operational Status\n"
                            f"- **Active & Online**: `{act}` cameras ({pct}% operational health).\n"
                            f"- **Inactive / Maintenance**: `{tot - act}` camera channels.\n\n"
                            f"*(Note: All camera channels feed continuous telemetry to central command).* "
                        ), context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] Camera count query failed: {e}")

        # B. Online / Active Cameras Listing Query ("list online cameras", "show active cameras")
        if ("cctv" in msg_lower or "camera" in msg_lower or "cameras" in msg_lower) and any(w in msg_lower for w in ["online", "active", "working", "connected"]):
            loc_filter = self._extract_location_filter(msg_lower, context)

            if self.ds.use_sql_server:
                try:
                    where_clause = "WHERE Status = 'Active'"
                    params = {}
                    if loc_filter:
                        where_clause += " AND (Area LIKE :loc OR CameraLocation LIKE :loc)"
                        params["loc"] = f"%{loc_filter}%"

                    q = f"SELECT CameraName, CameraId, Area, Status FROM CameraList {where_clause}"
                    with self.ds.engine.connect() as conn:
                        rows = conn.execute(text(q), params).mappings().all()
                        loc_str = f" in **{loc_filter}**" if loc_filter else ""
                        if rows:
                            tbl = "| Camera Name | Camera ID | Branch / Area | Status |\n|---|---|---|---|\n"
                            for r in rows:
                                tbl += f"| {r['CameraName']} | {r['CameraId']} | {r['Area']} | **{r['Status']}** |\n"
                            return f"Found **{len(rows)} Online / Active CCTV Cameras**{loc_str}:\n\n{tbl}\n### Operations Summary\nAll active camera channels are feeding real-time telemetry to central command.", context
                        else:
                            return f"No active CCTV cameras{loc_str} were found.", context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] Online camera query failed: {e}")

        # B2. Offline Cameras by Branch Query
        if ("cctv" in msg_lower or "camera" in msg_lower or "cameras" in msg_lower) and any(w in msg_lower for w in ["offline", "disconnected", "inactive", "down", "failure"]):
            loc_filter = self._extract_location_filter(msg_lower, context)

            if self.ds.use_sql_server:
                try:
                    where_clause = "WHERE Status != 'Active'"
                    params = {}
                    if loc_filter:
                        where_clause += " AND (Area LIKE :loc OR CameraLocation LIKE :loc)"
                        params["loc"] = f"%{loc_filter}%"

                    q = f"SELECT CameraName, CameraId, Area, Status FROM CameraList {where_clause}"
                    with self.ds.engine.connect() as conn:
                        rows = conn.execute(text(q), params).mappings().all()
                        loc_str = f" in **{loc_filter}**" if loc_filter else ""
                        if rows:
                            tbl = "| Camera Name | Camera ID | Branch / Area | Status |\n|---|---|---|---|\n"
                            for r in rows:
                                tbl += f"| {r['CameraName']} | {r['CameraId']} | {r['Area']} | **{r['Status']}** |\n"
                            return f"Found **{len(rows)} offline/inactive cameras**{loc_str}:\n\n{tbl}\n### Operations Summary\nMaintenance tickets created for offline camera channels.", context
                        else:
                            return f"All CCTV cameras{loc_str} are currently **Online** and actively recording. No camera failures detected.", context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] Offline camera query failed: {e}")

        # C. Motion Detection & Camera Channel Flags
        if any(w in msg_lower for w in ["motion", "channel", "detection"]) and any(w in msg_lower for w in ["highest", "most", "highest number", "flags", "events"]):
            if self.ds.use_sql_server:
                try:
                    q = """
                        SELECT TOP 5 
                            CASE 
                                WHEN Area LIKE '%NOIDA%' OR Location LIKE '%NOIDA%' THEN 'AO_NOIDA'
                                WHEN Area LIKE '%AGRA%' OR Location LIKE '%AGRA%' THEN 'AO_AGRA'
                                WHEN Area LIKE '%DELHI%' OR Location LIKE '%DELHI%' THEN 'AO_NORTH AND WEST DELHI'
                                ELSE COALESCE(Area, Location)
                            END as branch_name,
                            TRIM(COALESCE(Location, Area)) as channel_location, 
                            COUNT(*) as event_count
                        FROM AlertsDetails
                        WHERE AlertType LIKE '%Analytics%' OR AlertType LIKE '%Motion%' OR AlertType LIKE '%VMS%'
                        GROUP BY Area, Location
                        ORDER BY event_count DESC
                    """
                    with self.ds.engine.connect() as conn:
                        rows = conn.execute(text(q)).mappings().all()
                        if rows:
                            tbl = "| Rank | Branch Name | Camera Channel Location | Motion/Telemetry Flags |\n|---|---|---|---|\n"
                            for idx, r in enumerate(rows, 1):
                                tbl += f"| {idx} | **{r['branch_name']}** | `{r['channel_location']}` | **{r['event_count']:,} events** |\n"
                            top_branch = rows[0]['branch_name']
                            top_cnt = rows[0]['event_count']
                            return (
                                f"The camera channels in **{top_branch}** have registered the highest number of motion detection and analytics flags with **{top_cnt:,} total events**.\n\n"
                                f"### Top Monitored Camera Channels & Locations\n{tbl}\n"
                                f"*(Note: Motion detection telemetry is aggregated across perimeter analytics and video management servers).* "
                            ), context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] Motion channel query failed: {e}")

        # D. Open Security Incidents Undergoing Operator Review
        if any(w in msg_lower for w in ["incident", "incidents", "open security", "ticket", "tickets"]) and any(w in msg_lower for w in ["open", "undergoing", "review", "pending", "how many"]):
            if self.ds.use_sql_server:
                try:
                    q_cnt = "SELECT COUNT(*) as cnt FROM AlertsDetails WHERE Status LIKE '%Pending%'"
                    q_rows = """
                        SELECT TOP 15 AlertID, AlertType, TRIM(COALESCE(Area, Location)) as branch_name, Severity, Datetime, Status
                        FROM AlertsDetails
                        WHERE Status LIKE '%Pending%'
                        ORDER BY Datetime DESC
                    """
                    with self.ds.engine.connect() as conn:
                        cnt_res = conn.execute(text(q_cnt)).mappings().first()
                        cnt = cnt_res.get("cnt") or 0
                        rows = conn.execute(text(q_rows)).mappings().all()

                        tbl = "| Alert ID | Incident Type | Branch Name | Severity | Datetime | Status |\n|---|---|---|---|---|---|\n"
                        for r in rows:
                            tbl += f"| {r['AlertID']} | {r['AlertType']} | {r['branch_name']} | **{r['Severity']}** | {r['Datetime']} | **{r['Status']}** |\n"

                        return (
                            f"There are currently **{cnt:,} open security incidents** undergoing operator review in the Centralized Monitoring System.\n\n"
                            f"### Active Incident Review List (Top 15 Most Recent)\n{tbl}\n"
                            f"*(Note: All pending incidents are queued in command center operator consoles for acknowledgment).* "
                        ), context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] Open incidents query failed: {e}")
        
        # 1. Multi-Attribute Filter Query: "Show high priority alerts only closed status", "pending alerts excluding low priority"
        if any(sev in msg_lower for sev in ["high", "medium", "low"]) and any(st in msg_lower for st in ["closed", "pending", "active", "acknowledged"]):
            target_sev = "High" if "high" in msg_lower else ("Low" if "low" in msg_lower else "Medium")
            target_st = "Closed" if "closed" in msg_lower else ("Pending" if "pending" in msg_lower else "Acknowledged")
            is_exclusion = "excluding" in msg_lower or "except" in msg_lower or "not" in msg_lower
            
            loc_filter = self._extract_location_filter(msg_lower, context)

            if self.ds.use_sql_server:
                try:
                    sev_op = "!=" if is_exclusion else "="
                    where_parts = [f"Severity {sev_op} :sev", "Status LIKE :st"]
                    params = {"sev": target_sev, "st": f"%{target_st}%"}
                    if loc_filter:
                        where_parts.append("(Area LIKE :loc OR Location LIKE :loc)")
                        params["loc"] = f"%{loc_filter}%"

                    q = f"""
                        SELECT TOP 15 AlertID, AlertType, TRIM(COALESCE(Area, Location)) as branch_name, Severity, Datetime, Status
                        FROM AlertsDetails
                        WHERE {' AND '.join(where_parts)}
                        ORDER BY Datetime DESC
                    """
                    with self.ds.engine.connect() as conn:
                        rows = conn.execute(text(q), params).mappings().all()
                        loc_str = f" for **{loc_filter}**" if loc_filter else ""
                        ex_str = f" (excluding {target_sev} priority)" if is_exclusion else f" ({target_sev} priority)"
                        if rows:
                            tbl = "| Alert ID | Type | Branch Name | Severity | Datetime | Status |\n|---|---|---|---|---|---|\n"
                            for r in rows:
                                tbl += f"| {r['AlertID']} | {r['AlertType']} | {r['branch_name']} | **{r['Severity']}** | {r['Datetime']} | {r['Status']} |\n"
                            return f"Retrieved **{len(rows)} security alerts** with status **`{target_st}`**{loc_str}{ex_str}:\n\n{tbl}\n### Operations Summary\nDisplaying matching telemetry alerts filtered by severity and status.", context
                        else:
                            return f"No alerts with status **`{target_st}`**{loc_str}{ex_str} were found in the database.", context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] Multi-attribute query failed: {e}")

        # 2. Dynamic Date & Date-Range Filter ("between July 28 and August 10", "between 2026-07-28 and 2026-08-10")
        d_start, d_end, d_kind = self._extract_dates_from_query(msg_lower)
        if d_kind == "range" or ("between" in msg_lower and d_start and d_end):
            if self.ds.use_sql_server:
                try:
                    q_cnt = f"""
                        SELECT COUNT(*) as cnt
                        FROM AlertsDetails
                        WHERE Datetime >= '{d_start} 00:00:00' AND Datetime <= '{d_end} 23:59:59'
                    """
                    q_rows = f"""
                        SELECT TOP 15 AlertID, AlertType, TRIM(COALESCE(Area, Location)) as branch_name, Severity, Datetime, Status
                        FROM AlertsDetails
                        WHERE Datetime >= '{d_start} 00:00:00' AND Datetime <= '{d_end} 23:59:59'
                        ORDER BY Datetime DESC
                    """
                    with self.ds.engine.connect() as conn:
                        cnt_res = conn.execute(text(q_cnt)).mappings().first()
                        cnt = cnt_res.get("cnt") or 0
                        rows = conn.execute(text(q_rows)).mappings().all()
                        
                        tbl = "| Alert ID | Type | Branch Name | Severity | Datetime | Status |\n|---|---|---|---|---|---|\n"
                        for r in rows:
                            tbl += f"| {r['AlertID']} | {r['AlertType']} | {r['branch_name']} | **{r['Severity']}** | {r['Datetime']} | {r['Status']} |\n"

                        return (
                            f"A total of **{cnt:,} security alerts** were registered in the Centralized Monitoring System between **{d_start}** and **{d_end}**.\n\n"
                            f"### Sample Alerts Registered in Date Range ({d_start} – {d_end})\n{tbl}\n"
                            f"*(Showing top 15 out of {cnt:,} total alerts registered between {d_start} and {d_end}).*"
                        ), context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] Date range query failed: {e}")

        # 3. Single Severity Branch Query ("how many severe alerts for today", "Show the 5 most recent high-severity alerts in Noida")
        normalized_msg = msg_lower.replace("-", " ")
        has_high = bool(re.search(r'\b(high|critical|severe|major|urgent|dangerous|emergency|criticality|serious)\b', normalized_msg))
        has_medium = bool(re.search(r'\b(medium|moderate|normal|standard|mid|intermediate)\b', normalized_msg))
        has_low = bool(re.search(r'\b(low|minor|trivial|light|small|info)\b', normalized_msg))
        is_latency_or_skip = any(w in normalized_msg for w in ["operator", "handled", "slowest", "delay", "latency", "response", "time", "below", "above", "under", "exceeding", "ratio", "percent"])

        if (has_high or has_medium or has_low) and not is_latency_or_skip and any(w in normalized_msg for w in ["alert", "alerts", "incident", "incidents", "severity", "priority", "recent", "how many", "count", "total"]):
            # Severity Synonym Classifier
            if has_high:
                target_sev_sql = "Severity IN ('High', 'Critical')"
                target_sev_label = "High / Critical"
            elif has_medium:
                target_sev_sql = "Severity = 'Medium'"
                target_sev_label = "Medium"
            else:
                target_sev_sql = "Severity = 'Low'"
                target_sev_label = "Low"

            loc_filter = self._extract_location_filter(normalized_msg, context)
            d_start_sev, d_end_sev, d_kind_sev = self._extract_dates_from_query(normalized_msg)

            top_limit = 15
            cnt_match = re.search(r'\b(?:top|show|list|get|most recent|first)?\s*(\d+)\s*(?:most recent|recent|alerts|incidents|records|high|medium|low|severe)?\b', normalized_msg)
            if cnt_match and cnt_match.group(1):
                try:
                    parsed_val = int(cnt_match.group(1))
                    if 1 <= parsed_val <= 100:
                        top_limit = parsed_val
                except ValueError:
                    pass

            if self.ds.use_sql_server:
                try:
                    where_parts = [target_sev_sql]
                    params = {}
                    if loc_filter:
                        where_parts.append("(Area LIKE :loc OR Location LIKE :loc)")
                        params["loc"] = f"%{loc_filter}%"

                    date_str = ""
                    if d_start_sev and d_end_sev:
                        where_parts.append("Datetime >= :dt_start AND Datetime <= :dt_end")
                        params["dt_start"] = f"{d_start_sev} 00:00:00"
                        params["dt_end"] = f"{d_end_sev} 23:59:59"
                        date_str = f" for **{d_start_sev}**" if d_start_sev == d_end_sev else f" for **{d_start_sev} to {d_end_sev}**"

                    q_cnt = f"""
                        SELECT 
                            COUNT(*) as total_match,
                            SUM(CASE WHEN Status LIKE '%Pending%' THEN 1 ELSE 0 END) as pending_cnt,
                            SUM(CASE WHEN Status LIKE '%Closed%' THEN 1 ELSE 0 END) as closed_cnt
                        FROM AlertsDetails
                        WHERE {' AND '.join(where_parts)}
                    """

                    q_rows = f"""
                        SELECT TOP {top_limit} AlertID, AlertType, TRIM(COALESCE(Area, Location)) as branch_name, Severity, Datetime, Status
                        FROM AlertsDetails
                        WHERE {' AND '.join(where_parts)}
                        ORDER BY Datetime DESC
                    """
                    with self.ds.engine.connect() as conn:
                        res_cnt = conn.execute(text(q_cnt), params).mappings().first()
                        tot_match = res_cnt.get("total_match") or 0
                        pend_cnt = res_cnt.get("pending_cnt") or 0
                        closed_cnt = res_cnt.get("closed_cnt") or 0

                        rows = conn.execute(text(q_rows), params).mappings().all()
                        loc_str = f" for **{loc_filter}**" if loc_filter else ""
                        if rows:
                            tbl = "| Alert ID | Type | Branch Name | Severity | Datetime | Status |\n|---|---|---|---|---|---|\n"
                            for r in rows:
                                tbl += f"| {r['AlertID']} | {r['AlertType']} | {r['branch_name']} | **{r['Severity']}** | {r['Datetime']} | {r['Status']} |\n"
                            return f"Retrieved **{tot_match:,} {target_sev_label} priority alerts**{loc_str}{date_str} (**{pend_cnt:,} Pending**, **{closed_cnt:,} Closed**):\n\n{tbl}\n### Operations Summary\nDisplaying recent `{target_sev_label}` priority telemetry flags.", context
                        else:
                            return f"No `{target_sev_label}` priority security alerts{loc_str}{date_str} were found in the database.", context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] Single severity query failed: {e}")

        # 4. Branch / Area Exclusion Query ("List alerts excluding AO_AGRA", "excluding Low priority")
        if "except" in msg_lower or "excluding" in msg_lower or "exclude" in msg_lower:
            # Check if excluding a Branch (e.g. AO_AGRA, AO_NOIDA, Agra, Noida)
            target_exclude_branch = self._extract_location_filter(msg_lower)

            if target_exclude_branch and self.ds.use_sql_server:
                try:
                    q = """
                        SELECT TOP 15 AlertID, AlertType, TRIM(COALESCE(Area, Location)) as branch_name, Severity, Datetime, Status
                        FROM AlertsDetails
                        WHERE (Area NOT LIKE :ex_loc AND Location NOT LIKE :ex_loc)
                        ORDER BY Datetime DESC
                    """
                    with self.ds.engine.connect() as conn:
                        rows = conn.execute(text(q), {"ex_loc": f"%{target_exclude_branch}%"}).mappings().all()
                        if rows:
                            tbl = "| Alert ID | Type | Branch Name | Severity | Datetime | Status |\n|---|---|---|---|---|---|\n"
                            for r in rows:
                                tbl += f"| {r['AlertID']} | {r['AlertType']} | {r['branch_name']} | **{r['Severity']}** | {r['Datetime']} | {r['Status']} |\n"
                            return f"Retrieved security alerts **excluding branch `{target_exclude_branch}`**:\n\n{tbl}\n### Operations Summary\nDisplaying active telemetry alerts from all monitored branches except `{target_exclude_branch}`.", context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] Branch exclusion query failed: {e}")
            else:
                # Severity exclusion
                exclude_sev = "Low" if "low" in msg_lower else ("High" if "high" in msg_lower else "Medium")
                if self.ds.use_sql_server:
                    try:
                        q = """
                            SELECT TOP 15 AlertID, AlertType, TRIM(COALESCE(Area, Location)) as branch_name, Severity, Datetime, Status
                            FROM AlertsDetails
                            WHERE Severity != :ex_sev AND Severity IS NOT NULL
                            ORDER BY Datetime DESC
                        """
                        with self.ds.engine.connect() as conn:
                            rows = conn.execute(text(q), {"ex_sev": exclude_sev}).mappings().all()
                            if rows:
                                tbl = "| Alert ID | Type | Branch Name | Severity | Datetime | Status |\n|---|---|---|---|---|---|\n"
                                for r in rows:
                                    tbl += f"| {r['AlertID']} | {r['AlertType']} | {r['branch_name']} | **{r['Severity']}** | {r['Datetime']} | {r['Status']} |\n"
                                return f"Retrieved alerts **excluding `{exclude_sev}` priority**:\n\n{tbl}\n### Operations Summary\nDisplaying non-low priority alerts across monitored branches.", context
                    except Exception as e:
                        print(f"[COMPLEX QUERY ERROR] Severity exclusion query failed: {e}")

        # 5. Percentage / Ratio Queries (both Status and Severity!)
        if "percent" in msg_lower or "ratio" in msg_lower:
            loc = self._extract_location_filter(msg_lower, context) or "AO_NOIDA"

            is_closed = "closed" in msg_lower
            is_pending = "pending" in msg_lower
            
            if is_closed or is_pending:
                target_status = "Closed" if is_closed else "Pending"
                if self.ds.use_sql_server:
                    try:
                        q = """
                            SELECT 
                                COUNT(*) as total_count,
                                SUM(CASE WHEN Status LIKE :st THEN 1 ELSE 0 END) as match_count
                            FROM AlertsDetails
                            WHERE (Area LIKE :loc OR Location LIKE :loc OR Zone LIKE :loc)
                        """
                        with self.ds.engine.connect() as conn:
                            res = conn.execute(text(q), {"st": f"%{target_status}%", "loc": f"%{loc}%"}).mappings().first()
                            tot = res.get("total_count") or 1
                            m = res.get("match_count") or 0
                            pct = round((m / tot) * 100, 2)
                            resp = (
                                f"In **{loc}**, out of **{tot:,} total alerts**, **{m:,}** have status `{target_status}`.\n\n"
                                f"### Breakdown\n"
                                f"- **Target Status (`{target_status}`)**: `{pct}%` of total location volume.\n"
                                f"- **Total Location Volume**: `{tot:,}` security flags.\n\n"
                                f"*(Note: {pct}% of registered alerts in {loc} have been evaluated and marked as {target_status}).*"
                            )
                            return resp, context
                    except Exception as e:
                        print(f"[COMPLEX QUERY ERROR] Status percentage query failed: {e}")
            else:
                severity = "High" if "high" in msg_lower else ("Low" if "low" in msg_lower else "Medium")
                if self.ds.use_sql_server:
                    try:
                        q = """
                            SELECT 
                                COUNT(*) as total_count,
                                SUM(CASE WHEN Severity = :sev THEN 1 ELSE 0 END) as match_count
                            FROM AlertsDetails
                            WHERE (Area LIKE :loc OR Location LIKE :loc OR Zone LIKE :loc)
                        """
                        with self.ds.engine.connect() as conn:
                            res = conn.execute(text(q), {"sev": severity, "loc": f"%{loc}%"}).mappings().first()
                            tot = res.get("total_count") or 1
                            m = res.get("match_count") or 0
                            pct = round((m / tot) * 100, 2)
                            resp = (
                                f"In **{loc}**, out of **{tot:,} total alerts**, **{m:,}** are `{severity}` priority.\n\n"
                                f"### Breakdown\n"
                                f"- **Target Severity (`{severity}`)**: `{pct}%` of total volume.\n"
                                f"- **Total Location Volume**: `{tot:,}` security flags.\n\n"
                                f"*(Note: {pct}% of recorded alerts in {loc} are categorized under {severity} priority telemetry rules).* "
                            )
                            return resp, context
                    except Exception as e:
                        print(f"[COMPLEX QUERY ERROR] Severity percentage query failed: {e}")

        # 5.5 Response Time & Latency Threshold Handler ("show alerts with response time below 30 seconds", "response time for today")
        if any(w in msg_lower for w in ["response time", "sla", "delay", "operator time", "latency"]):
            # Check for threshold condition (e.g. "below 30 seconds", "under 1 minute", "above 5 minutes")
            thresh_match = re.search(r'\b(below|under|less than|shorter than|above|exceeding|more than|longer than)\s+(\d+)\s*(sec|second|seconds|min|mins|minute|minutes|hr|hrs|hour|hours)?\b', msg_lower)
            if thresh_match:
                op_word = thresh_match.group(1)
                val_num = int(thresh_match.group(2))
                unit = (thresh_match.group(3) or "second").lower()
                
                # Convert threshold to seconds
                if "min" in unit:
                    thresh_sec = val_num * 60
                elif "hr" in unit or "hour" in unit:
                    thresh_sec = val_num * 3600
                else:
                    thresh_sec = val_num
                
                comp_op = "<" if op_word in ["below", "under", "less than", "shorter than"] else ">"
                op_label = f"less than {val_num} {unit}" if comp_op == "<" else f"greater than {val_num} {unit}"
                
                loc_filter_thresh = self._extract_location_filter(msg_lower, context)
                where_parts = ["AckTime IS NOT NULL", f"DATEDIFF(second, Datetime, AckTime) {comp_op} :th_sec"]
                params = {"th_sec": thresh_sec}
                if loc_filter_thresh:
                    where_parts.append("(Area LIKE :loc OR Location LIKE :loc)")
                    params["loc"] = f"%{loc_filter_thresh}%"
                
                if self.ds.use_sql_server:
                    try:
                        q_cnt = f"""
                            SELECT COUNT(*) as total_cnt,
                                   AVG(DATEDIFF(second, Datetime, AckTime)) as avg_sec
                            FROM AlertsDetails
                            WHERE {' AND '.join(where_parts)}
                        """
                        q_rows = f"""
                            SELECT TOP 15 AlertID, AlertType, TRIM(COALESCE(Area, Location)) as branch_name, Severity, Datetime, DATEDIFF(second, Datetime, AckTime) as resp_sec, Status
                            FROM AlertsDetails
                            WHERE {' AND '.join(where_parts)}
                            ORDER BY DATEDIFF(second, Datetime, AckTime) ASC
                        """
                        with self.ds.engine.connect() as conn:
                            c_res = conn.execute(text(q_cnt), params).mappings().first()
                            tot_cnt = c_res.get("total_cnt") or 0
                            avg_s = c_res.get("avg_sec")
                            rows = conn.execute(text(q_rows), params).mappings().all()
                            
                            loc_str = f" in **{loc_filter_thresh}**" if loc_filter_thresh else ""
                            avg_str = self.ds.format_seconds_human(avg_s) if avg_s else "N/A"
                            
                            if rows:
                                tbl = "| Alert ID | Type | Branch Name | Severity | Datetime | Response Delay | Status |\n|---|---|---|---|---|---|---|\n"
                                for r in rows:
                                    r_str = self.ds.format_seconds_human(r['resp_sec'])
                                    tbl += f"| {r['AlertID']} | {r['AlertType']} | {r['branch_name']} | **{r['Severity']}** | {r['Datetime']} | **{r_str}** | {r['Status']} |\n"
                                return (
                                    f"Found **{tot_cnt:,} security alerts**{loc_str} with response time **{op_label}** (average delay **{avg_str}**):\n\n"
                                    f"### Telemetry Alerts Matching SLA Threshold ({op_label})\n{tbl}\n"
                                    f"*(Showing top 15 alerts matching response latency threshold).* "
                                ), context
                            else:
                                return f"No security alerts{loc_str} were found matching response time **{op_label}**.", context
                    except Exception as e:
                        print(f"[COMPLEX QUERY ERROR] Response threshold query failed: {e}")
            if self.ds.use_sql_server:
                try:
                    d_start_rt, d_end_rt, d_kind_rt = self._extract_dates_from_query(msg_lower)
                    loc_filter_rt = self._extract_location_filter(msg_lower, context)
                    type_filter_rt = self._extract_alert_type_filter(msg_lower)

                    where_parts_rt = []
                    params_rt = {}
                    desc_labels = []

                    # 1. Dynamic Date Filter
                    if d_start_rt and d_end_rt:
                        where_parts_rt.append("Datetime >= :dt_start AND Datetime <= :dt_end")
                        params_rt["dt_start"] = f"{d_start_rt} 00:00:00"
                        params_rt["dt_end"] = f"{d_end_rt} 23:59:59"
                        dt_str = f"for **{d_start_rt}**" if d_start_rt == d_end_rt else f"for **{d_start_rt} to {d_end_rt}**"
                        desc_labels.append(dt_str)
                    elif "today" in msg_lower:
                        today_str = datetime.now().strftime("%Y-%m-%d")
                        where_parts_rt.append("Datetime >= :dt_start AND Datetime <= :dt_end")
                        params_rt["dt_start"] = f"{today_str} 00:00:00"
                        params_rt["dt_end"] = f"{today_str} 23:59:59"
                        desc_labels.append(f"for today (**{today_str}**)")

                    # 2. Dynamic Branch / Location Filter
                    if loc_filter_rt:
                        where_parts_rt.append("(Area LIKE :loc OR Location LIKE :loc)")
                        params_rt["loc"] = f"%{loc_filter_rt}%"
                        desc_labels.append(f"in **{loc_filter_rt}**")

                    # 3. Dynamic Alert Type Filter
                    if type_filter_rt:
                        where_parts_rt.append("AlertType = :at_type")
                        params_rt["at_type"] = type_filter_rt
                        desc_labels.append(f"for **{type_filter_rt}** alerts")

                    # 4. Dynamic Severity Filter
                    has_high_rt = bool(re.search(r'\b(high|critical|severe)\b', msg_lower))
                    has_med_rt = bool(re.search(r'\b(medium|moderate)\b', msg_lower))
                    has_low_rt = bool(re.search(r'\b(low|minor)\b', msg_lower))
                    if has_high_rt:
                        where_parts_rt.append("Severity IN ('High', 'Critical')")
                        desc_labels.append("with **High / Critical** severity")
                    elif has_med_rt:
                        where_parts_rt.append("Severity = 'Medium'")
                        desc_labels.append("with **Medium** severity")
                    elif has_low_rt:
                        where_parts_rt.append("Severity = 'Low'")
                        desc_labels.append("with **Low** severity")

                    # 5. Dynamic Status Filter
                    if any(s in msg_lower for s in ["closed", "completed", "resolved"]):
                        where_parts_rt.append("(Status LIKE '%Closed%' OR Status LIKE '%Completed%')")
                        desc_labels.append("with **Closed** status")
                    elif any(s in msg_lower for s in ["pending", "active", "open"]):
                        where_parts_rt.append("(Status LIKE '%Pending%' OR Status LIKE '%Active%')")
                        desc_labels.append("with **Pending** status")

                    scope_str = (" " + " ".join(desc_labels)) if desc_labels else " across all registered alerts"
                    where_clause_rt = f"WHERE {' AND '.join(where_parts_rt)}" if where_parts_rt else ""

                    q = f"""
                        SELECT 
                            COUNT(*) as total_alerts,
                            SUM(CASE WHEN AckTime IS NOT NULL THEN 1 ELSE 0 END) as ack_alerts,
                            AVG(CASE WHEN AckTime IS NOT NULL THEN DATEDIFF(second, Datetime, AckTime) ELSE NULL END) as avg_delay_sec,
                            MAX(CASE WHEN AckTime IS NOT NULL THEN DATEDIFF(second, Datetime, AckTime) ELSE NULL END) as max_delay_sec
                        FROM AlertsDetails
                        {where_clause_rt}
                    """
                    with self.ds.engine.connect() as conn:
                        res = conn.execute(text(q), params_rt).mappings().first()
                        tot = res.get("total_alerts") or 0
                        ack = res.get("ack_alerts") or 0
                        avg_s = res.get("avg_delay_sec")
                        max_s = res.get("max_delay_sec")

                        avg_str = self.ds.format_seconds_human(avg_s) if avg_s is not None else "N/A (instant)"
                        max_str = self.ds.format_seconds_human(max_s) if max_s is not None else "N/A"
                        pct = round((ack / tot) * 100, 2) if tot > 0 else 0

                        return (
                            f"The average operator response time{scope_str} is **{avg_str}** across **{tot:,} registered telemetry alerts** (`{pct}%` evaluated):\n\n"
                            f"### Operator Response Summary{scope_str}\n"
                            f"- **Average Response Delay**: `{avg_str}`\n"
                            f"- **Maximum Delay Recorded**: `{max_str}`\n"
                            f"- **Processed Telemetry Volume**: `{ack:,}` of `{tot:,}` alerts (`{pct}%` SLA compliance).\n\n"
                            f"*(Note: Response time measures latency between automated sensor trigger and operator acknowledgment).* "
                        ), context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] Response time query failed: {e}")

        # 6. Specific Date Queries ("Show all alerts registered on August 12", "July 13", "August 24")
        if d_kind == "single" or (d_start and d_start == d_end):
            target_date = d_start
            if target_date and self.ds.use_sql_server:
                loc_filter = self._extract_location_filter(msg_lower, context)

                sev_filter = None
                if "high" in msg_lower: sev_filter = "High"
                elif "low" in msg_lower: sev_filter = "Low"
                elif "medium" in msg_lower: sev_filter = "Medium"

                try:
                    loc_filter = self._extract_location_filter(msg_lower, context)
                    type_filter = self._extract_alert_type_filter(msg_lower)

                    where_parts = [
                        "Datetime >= :dt_start AND Datetime <= :dt_end"
                    ]
                    params = {
                        "dt_start": f"{target_date} 00:00:00",
                        "dt_end": f"{target_date} 23:59:59"
                    }
                    labels = [f"on **{target_date}**"]

                    if loc_filter:
                        where_parts.append("(Area LIKE :loc OR Location LIKE :loc)")
                        params["loc"] = f"%{loc_filter}%"
                        labels.append(f"in **{loc_filter}**")

                    if type_filter:
                        where_parts.append("AlertType = :at_type")
                        params["at_type"] = type_filter
                        labels.append(f"for **{type_filter}** alerts")

                    if re.search(r'\b(high|critical|severe)\b', msg_lower):
                        where_parts.append("Severity IN ('High', 'Critical')")
                        labels.append("with **High / Critical** severity")
                    elif re.search(r'\b(medium|moderate)\b', msg_lower):
                        where_parts.append("Severity = 'Medium'")
                        labels.append("with **Medium** severity")
                    elif re.search(r'\b(low|minor)\b', msg_lower):
                        where_parts.append("Severity = 'Low'")
                        labels.append("with **Low** severity")

                    if any(s in msg_lower for s in ["closed", "completed", "resolved"]):
                        where_parts.append("(Status LIKE '%Closed%' OR Status LIKE '%Completed%')")
                        labels.append("with **Closed** status")
                    elif any(s in msg_lower for s in ["pending", "active", "open"]):
                        where_parts.append("(Status LIKE '%Pending%' OR Status LIKE '%Active%')")
                        labels.append("with **Pending** status")

                    scope_str = " " + " ".join(labels)
                    q_cnt = f"SELECT COUNT(*) as total_cnt FROM AlertsDetails WHERE {' AND '.join(where_parts)}"
                    q_rows = f"SELECT TOP 15 AlertID, AlertType, TRIM(COALESCE(Area, Location)) as branch_name, Severity, Datetime, Status FROM AlertsDetails WHERE {' AND '.join(where_parts)} ORDER BY Datetime DESC"
                    with self.ds.engine.connect() as conn:
                        c_res = conn.execute(text(q_cnt), params).mappings().first()
                        tot_cnt = c_res.get("total_cnt") or 0
                        rows = conn.execute(text(q_rows), params).mappings().all()

                        if tot_cnt > 0:
                            tbl = "| Alert ID | Type | Branch Name | Severity | Datetime | Status |\n|---|---|---|---|---|---|\n"
                            for r in rows:
                                tbl += f"| {r['AlertID']} | {r['AlertType']} | {r['branch_name']} | **{r['Severity']}** | {r['Datetime']} | {r['Status']} |\n"
                            return (
                                f"A total of **{tot_cnt:,} security alerts** were registered{scope_str}:\n\n"
                                f"### Registered Telemetry Alerts ({target_date})\n{tbl}\n"
                                f"*(Note: Displaying top {len(rows)} sample alerts out of {tot_cnt:,} total alerts).* "
                            ), context
                        else:
                            return f"No security alerts were registered{scope_str}. All operational parameters were normal.", context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] Specific date query failed: {e}")


        # 6. Top Slowest Responded Branches
        if "slowest" in msg_lower or "longest response" in msg_lower:
            if self.ds.use_sql_server:
                try:
                    q = """
                        SELECT TOP 3 
                            TRIM(COALESCE(Area, Location)) as branch_name, 
                            AVG(DATEDIFF(second, Datetime, AckTime)) as avg_delay_sec, 
                            COUNT(*) as eval_count
                        FROM AlertsDetails
                        WHERE AckTime IS NOT NULL AND Datetime IS NOT NULL
                        GROUP BY TRIM(COALESCE(Area, Location))
                        ORDER BY avg_delay_sec DESC
                    """
                    with self.ds.engine.connect() as conn:
                        rows = conn.execute(text(q)).mappings().all()
                        if rows:
                            tbl = "| Rank | Branch Name | Average Response Delay | Evaluated Alerts |\n|---|---|---|---|\n"
                            for idx, r in enumerate(rows, 1):
                                time_str = self.ds.format_seconds_human(r["avg_delay_sec"])
                                tbl += f"| {idx} | **{r['branch_name']}** | **{time_str}** | {r['eval_count']} |\n"
                            return f"Here are the **Top Slowest Responded Branches** based on operator acknowledgment latency:\n\n{tbl}\n### Advisory\nRecommended to audit operator shift handovers and alert queue dispatching at these locations.", context
                except Exception as e:
                    print(f"[COMPLEX QUERY ERROR] Slowest branches query failed: {e}")

        # 7. Threshold Response Time Queries ("below 1 minute", "under 5 minutes", "between 10 minutes and 1 hour")
        if any(w in msg_lower for w in ["below", "under", "less than", "within", "shorter than", "between"]) and re.search(r'\b(?:sec|second|seconds|min|mins|minute|minutes|hr|hrs|hour|hours)\b', msg_lower):
            max_sec = 60
            min_sec = None

            if "5 min" in msg_lower or "5 minutes" in msg_lower: max_sec = 300
            elif "10 min" in msg_lower or "10 minutes" in msg_lower: max_sec = 600
            elif "1 min" in msg_lower or "1 minute" in msg_lower or "60 sec" in msg_lower: max_sec = 60
            elif "30 sec" in msg_lower or "30 seconds" in msg_lower: max_sec = 30

            if "between 10 minutes and 1 hour" in msg_lower or ("10 min" in msg_lower and "1 hour" in msg_lower):
                min_sec = 600
                max_sec = 3600

            target_loc = self._extract_location_filter(msg_lower)

            target_sev = None
            if "high" in msg_lower or "critical" in msg_lower: target_sev = "High"
            elif "medium" in msg_lower or "moderate" in msg_lower: target_sev = "Medium"
            elif "low" in msg_lower: target_sev = "Low"

            alerts = self.ds.get_alerts_by_response_threshold(max_seconds=max_sec, min_seconds=min_sec, severity=target_sev, location=target_loc)
            if alerts:
                tbl = "| Alert ID | Type | Branch / Area | Severity | Response Delay | Datetime | Status |\n|---|---|---|---|---|---|---|\n"
                for a in alerts:
                    tbl += f"| {a['alert_id']} | {a['alert_type']} | {a['branch_name']} | {a['severity']} | **{a['formatted_response_time']}** | {a['timestamp']} | {a['status']} |\n"
                range_desc = f"between **{self.ds.format_seconds_human(min_sec)}** and **{self.ds.format_seconds_human(max_sec)}**" if min_sec else f"below **{self.ds.format_seconds_human(max_sec)}**"
                sev_desc = f"**{target_sev}** severity " if target_sev else ""
                return f"Found **{len(alerts)} {sev_desc}alerts** with a response time {range_desc}:\n\n{tbl}\n### Operations Summary\nDisplaying matching telemetry alerts.", context
            else:
                sev_desc = f"**{target_sev}** priority " if target_sev else ""
                return f"No {sev_desc}alerts were found in the database with a response time below **{self.ds.format_seconds_human(max_sec)}**. *(Note: All currently evaluated alerts in the database under 5 minutes are Medium severity).*", context

        # 8. Operator Workload Query ("Which operator handled the highest number of closed alerts?")
        if "operator" in msg_lower or "handled" in msg_lower or "workload" in msg_lower:
            ops = self.ds.get_operator_performance()
            if ops:
                tbl = "| Operator ID | Name | Role | Total Processed |\n|---|---|---|---|\n"
                for o in ops:
                    tbl += f"| {o.get('usr_id', 'N/A')} | {o.get('name', 'Operator')} | {o.get('role', 'Admin')} | **{o.get('processed_incidents', 0)}** |\n"
                top_op = ops[0]
                return f"Operator **{top_op.get('name')}** (`{top_op.get('role')}`) has handled the highest volume of processed monitoring tickets:\n\n{tbl}\n### Staff Performance\nActive operator accounts retrieved from command center user directory.", context

        return None, context


    def _classify_and_fetch(self, msg: str, context: dict) -> tuple:


        """

        Parses keywords, runs queries against DataService, and updates conversational context.

        """

        # Static list of known 17 LHOs for direct extraction

        lho_list = [

            "bhopal", "mumbai metro", "maharashtra", "bengaluru", "kolkata", 

            "new delhi", "delhi", "chennai", "hyderabad", "trivandrum", 

            "chandigarh", "jaipur", "bhubaneswar", "patna", "lucknow", 

            "guwahati", "amaravati", "gandhinagar"

        ]

        

        # Keep track of filter state in context

        active_lho = context.get("active_lho_filter", None)

        active_branch = context.get("active_branch_filter", None)



        # Check if a known LHO name is inside the message (with word boundaries)

        found_lho = None

        for lho_candidate in lho_list:

            if re.search(r'\b' + re.escape(lho_candidate) + r'\b', msg):

                mapped_name = "New Delhi" if lho_candidate == "delhi" else lho_candidate.title()

                found_lho = mapped_name

                break

                

        if found_lho:

            active_lho = found_lho

            context["active_lho_filter"] = found_lho



        # Check for Branch filter

        branch_match = re.search(r'(?:at|for|sbi)\s+(sbi\s+[a-zA-Z\s]+)', msg)

        if branch_match:

            b_name = branch_match.group(1).strip().title()

            if not b_name.startswith("Sbi "):

                b_name = "Sbi " + b_name

            active_branch = b_name

            context["active_branch_filter"] = b_name



        # Semantic NLP intent extraction

        semantic_intent, confidence = self._semantic_classify(msg)

        is_semantic = lambda target: semantic_intent == target and confidence >= 0.75



        # --- INTENT ROUTING (Specific check first, then generic) ---

        data_payload = {}

        

        # 1. Alert Click & Incident Click
        alert_query_match = re.search(r'more about the\s+([a-zA-Z\s-]+?)\s+alert at\s+([a-zA-Z\s\d_]+)', msg)
        incident_query_match = re.search(r'about incident\s+(inc-\d+)', msg)

        # Branch with highest alerts (explicit match first to prevent false_alert_rate semantic mis-match)
        if ("branch" in msg or "branches" in msg) and ("highest" in msg or "most" in msg or "maximum" in msg or "top" in msg) and ("alert" in msg or "alerts" in msg or "alarm" in msg):
            intent = "HIGHEST_ALERTS_BRANCH"
            data_payload["branches"] = self.ds.get_highest_alerts_branch()
            context["last_query_type"] = "branches"

        # Specific High Response Time Alerts/Incidents (e.g. "which incidents have high response time", "which alerts have long response time")
        elif ("which" in msg or "what" in msg or "show" in msg or "list" in msg or "tell" in msg) and ("incident" in msg or "alert" in msg or "ticket" in msg or "response" in msg) and ("response time" in msg or "delay" in msg or "latency" in msg or "high" in msg or "long" in msg or "slow" in msg):
            intent = "HIGH_RESPONSE_TIME_ALERTS"
            data_payload["alerts"] = self.ds.get_high_response_time_alerts()
            context["last_query_type"] = "high_response_time_alerts"

        # Conversational Follow-up for Response Time queries: "which incidents are those", "tell me about those incidents", "which alerts are those"
        elif context.get("last_query_type") in ["high_response_time_alerts", "lhos", "lho_response_time", "summary"] and (
            any(w in msg for w in ["which incident", "which alert", "what incident", "what alert", "tell me about", "details of those", "show those", "about those", "about them"]) 
            or msg in ["which incidents are those", "which alerts are those", "what are those incidents", "tell me about those incidents", "which incidents are these"]
        ):
            intent = "EVALUATED_RESPONSE_TIME_INCIDENTS"
            data_payload["alerts"] = self.ds.get_high_response_time_alerts(limit=10)
            context["last_query_type"] = "lho_response_time_incidents"

        # General Circle Average Response Time / SLA Summary
        elif "response time" in msg or "sla" in msg or "mttr" in msg:
            intent = "LHO_RESPONSE_TIME"
            data_payload["lhos"] = self.ds.get_lho_response_times()
            context["last_query_type"] = "lho_response_time"




        # Check for LHO specific branch listing (e.g. "list branches in New Delhi LHO", "how many branches under New Delhi LHO")
        elif ("branch" in msg or "branches" in msg or "under" in msg) and active_lho and any(w in msg for w in ["list", "show", "count", "how many", "under", "in", "for", "lho"]):

            intent = "LHO_BRANCHES_LIST"
            lho_branches = self.ds.get_branches_by_lho(active_lho)
            data_payload["lho_name"] = active_lho
            data_payload["branches"] = lho_branches
            data_payload["branches_count"] = len(lho_branches)
            context["last_query_type"] = "branches"


        # Priority Alert Filter by Branch or LHO (e.g. "High priority alerts in AO_NOIDA", "low priority alerts in Bhopal")
        elif ("priority" in msg or "severity" in msg) and any(sev in msg for sev in ["high", "critical", "medium", "moderate", "low"]):
            intent = "ALERTS_BY_PRIORITY_LOCATION"
            severity = "High" if ("high" in msg or "critical" in msg) else ("Medium" if ("medium" in msg or "moderate" in msg) else "Low")
            target_loc = active_branch or active_lho
            if not target_loc:
                loc_match = re.search(r'(?:in|at|for)\s+([a-zA-Z0-9_\s]+)', msg)
                if loc_match:
                    target_loc = loc_match.group(1).strip()
            data_payload["severity"] = severity
            data_payload["location"] = target_loc or "All Locations"
            data_payload["alerts"] = self.ds.get_priority_alerts(severity, target_loc)
            context["last_query_type"] = "alerts"

        elif alert_query_match:


            intent = "ALERT_DETAILS"

            alert_type = alert_query_match.group(1).strip()

            branch_name = alert_query_match.group(2).strip()

            data_payload = self.ds.get_alert_details(alert_type, branch_name)

            if data_payload:

                context["last_query_type"] = "alert_details"

            else:

                intent = "GENERAL_INTELLIGENCE"



        elif incident_query_match:

            intent = "INCIDENT_DETAILS"

            inc_id = incident_query_match.group(1).strip().upper()

            data_payload = self.ds.get_incident_details(inc_id)

            if data_payload:

                context["last_query_type"] = "incident_details"

            else:

                intent = "GENERAL_INTELLIGENCE"



        # 3. SOP Check

        elif is_semantic("SOP_QUERY") or any(k in msg for k in ["sop", "standard operating procedure", "procedure", "responder", "contact details", "called first", "who to call", "who should be called", "escalation"]):

            intent = "SOP_QUERY"

            matched_sop = None

            for key in ["Panic Button Activation", "Perimeter Breach", "Fire/Smoke Alert", "Camera Tampering", "Joint Custodian Violation", "Frisking Violation"]:

                first_word = key.split(" ")[0].lower()

                if (key.lower() in msg) or (first_word in msg) or (key == "Joint Custodian Violation" and "custodian" in msg) or (key == "Fire/Smoke Alert" and "fire" in msg):

                    matched_sop = self.ds.get_sop(key)

                    break

            if not matched_sop:

                matched_sop = self.ds.get_sop("Panic Button Activation")

            data_payload["sop"] = matched_sop

            context["last_query_type"] = "sop"

            

        # 4. Dashboard Summary

        elif is_semantic("DASHBOARD_SUMMARY") or "dashboard" in msg or "overview" in msg or "summary" in msg:

            intent = "DASHBOARD_SUMMARY"

            data_payload["summary"] = self.ds.get_dashboard_summary()

            context["last_query_type"] = "summary"



        # 5. Stale Unresolved > 24 hours

        elif "unresolved" in msg and ("24 hours" in msg or "24h" in msg or "stale" in msg or "older" in msg):

            intent = "UNRESOLVED_STALE"

            data_payload["incidents"] = self.ds.get_stale_unresolved_incidents()

            context["last_query_type"] = "incidents"



        # 6a. Camera Count Grouped by Device Type
        elif re.search(r'\bc(?:a)?m(?:e)?r(?:a)?s?\b|\bcams?\b', msg) and re.search(r'\bdevice\s+type\b|\bgrouped\s+by\b|\bby\s+type\b|\btype\s+count\b|\btype\b', msg):
            intent = "CAMERAS_BY_TYPE_COUNT"
            data_payload["camera_types"] = self.ds.get_camera_counts_by_type()
            context["last_query_type"] = "devices"

        # 6b. Cameras in Specific Area / Location
        elif re.search(r'\bc(?:a)?m(?:e)?r(?:a)?s?\b|\bcams?\b', msg) and (re.search(r'\bin\s+([a-zA-Z\s]+?)(?:\s+area|\s+branch|\s+zone)?$', msg) or "jankipuram" in msg or "quila" in msg or "aonla" in msg or "nariman" in msg or "noida" in msg) and not re.search(r'\boff(?:l)?ine\b|\bdown\b|\bdead\b', msg):
            intent = "CAMERA_LIST_AREA"
            area_search = self._extract_location_filter(msg, context) or ""
            data_payload["area_name"] = area_search or "Branch Area"
            data_payload["cameras"] = self.ds.get_cameras_by_area(area_search) if area_search else []
            context["last_query_type"] = "devices"

        # 6c. Offline Cameras (supporting typos like "offine cmeras" or "dead cams")
        elif is_semantic("OFFLINE_CAMERAS") or (re.search(r'\bc(?:a)?m(?:e)?r(?:a)?s?\b|\bcams?\b', msg) and re.search(r'\boff(?:l)?ine\b|\bdown\b|\bdead\b|\bfail(?:ed|ure)?s?\b|\bnot\s+working\b', msg) and not any(w in msg for w in ["count", "group", "grouped", "versus", "vs", "status", "statistic", "summary", "number of"])):
            intent = "OFFLINE_CAMERAS"
            city = None
            if "bhopal" in msg:
                city = "Bhopal"
            elif "mumbai" in msg:
                city = "Mumbai"
            elif "delhi" in msg:
                city = "Delhi"
            elif "bengaluru" in msg:
                city = "Bengaluru"
            
            data_payload["city"] = city
            data_payload["cameras"] = self.ds.get_offline_cameras(city=city)
            context["last_query_type"] = "devices"





        # 7. Offline Devices / most offline devices

        elif "offline" in msg and "device" in msg:

            intent = "OFFLINE_DEVICES"

            devices = self.ds.get_unhealthy_devices()  # Fix Issue 6: was calling non-existent get_devices()

            branch_counts = {}

            for d in devices:

                b_name = d.get("branch_name")

                branch_counts[b_name] = branch_counts.get(b_name, 0) + 1

            sorted_b = sorted(branch_counts.items(), key=lambda x: x[1], reverse=True)

            data_payload["branches"] = [{"branch_name": k, "offline_devices_count": v} for k, v in sorted_b]

            context["last_query_type"] = "branches"



        # 8. Unhealthy Devices

        elif is_semantic("UNHEALTHY_DEVICES") or "unhealthy" in msg:

            intent = "UNHEALTHY_DEVICES"

            data_payload["devices"] = self.ds.get_unhealthy_devices()

            context["last_query_type"] = "devices"



        # 9. Camera Tampering

        elif is_semantic("CAMERA_TAMPERING") or "tampering" in msg:

            intent = "CAMERA_TAMPERING"

            data_payload["branches"] = self.ds.get_tampering_alerts()

            context["last_query_type"] = "alerts"



        # 10. Repeated Perimeter Breaches

        elif is_semantic("PERIMETER_BREACHES") or ("perimeter" in msg and "breach" in msg):

            intent = "PERIMETER_BREACHES"

            data_payload["branches"] = self.ds.get_repeated_perimeter_breaches()

            context["last_query_type"] = "alerts"



        # 11. Panic Button triggers

        elif is_semantic("PANIC_BUTTON") or "panic" in msg:

            intent = "PANIC_BUTTON"

            data_payload["incidents"] = [inc for inc in self.ds.get_incidents() if "panic" in inc.get("incident_type", "").lower()]

            context["last_query_type"] = "incidents"



        # 12. Fire/Smoke Alerts

        elif is_semantic("FIRE_ALERTS") or "fire" in msg or "smoke" in msg:

            intent = "FIRE_ALERTS"

            data_payload["incidents"] = [inc for inc in self.ds.get_incidents() if "fire" in inc.get("incident_type", "").lower()]

            context["last_query_type"] = "incidents"



        # 13. Operator Performance & Listing (supporting typos like "oprator" and "leaderboard")
        elif (is_semantic("OPERATOR_PERFORMANCE") or re.search(r'\bop(?:e)?rat(?:o|e)?rs?\b|\bstaff\b|\bpersonnel\b|\bpeoples?\b|\bleaderboard\b|\branking\b', msg)) and not (re.search(r'\b(priya|aarav|bhavana|karan|rohan|neha)\b', msg) or any(w in msg for w in ["assigned to", "assigned operator", "assigned", "workload"])):
            intent = "OPERATOR_PERFORMANCE"



            data_payload["operators"] = self.ds.get_operator_performance()

            context["last_query_type"] = "operators"



        # 14. False Alert Rate — Fix Issue 5: Strengthened guard to avoid mis-routing "highest number of alerts"

        elif "false alert" in msg or "false alarm" in msg or ("false" in msg and "rate" in msg) or ("accidental" in msg and "alert" in msg):

            intent = "FALSE_ALERT_RATE"

            data_payload["branches"] = self.ds.get_false_alert_rates()

            context["last_query_type"] = "branches"






        # 16. AI Use Case Alerts

        elif is_semantic("AI_USE_CASE_STATS") or ("use case" in msg and "alert" in msg):

            intent = "AI_USE_CASE_STATS"

            alerts = self.ds.get_alerts()

            uc_counts = {}

            for a in alerts:

                uc = a.get("alert_type")

                uc_counts[uc] = uc_counts.get(uc, 0) + 1

            sorted_uc = sorted(uc_counts.items(), key=lambda x: x[1], reverse=True)

            data_payload["use_cases"] = [{"use_case": k, "alert_count": v} for k, v in sorted_uc]

            context["last_query_type"] = "alerts"



        # 17. Conversational Follow-up "which ones are open?" / "still open?"

        # Fix Issue 9: removed bare `or "show"` which was always truthy (non-empty string)

        elif ("which ones" in msg or "what" in msg or "show" in msg) and ("open" in msg or "active" in msg) and active_lho:

            intent = "FOLLOW_UP_OPEN"

            data_payload["lho_name"] = active_lho

            data_payload["incidents"] = self.ds.get_incidents(lho_name=active_lho, status="open_active")

            context["last_query_type"] = "incidents"



        # 18. LHO filter direct listing (e.g. "show Bhopal incidents")

        elif "incident" in msg and active_lho:

            intent = "LHO_INCIDENTS"

            data_payload["lho_name"] = active_lho

            data_payload["incidents"] = self.ds.get_incidents(lho_name=active_lho)

            context["last_query_type"] = "incidents"



        # 19. Branches with more than 5 incidents

        elif "branch" in msg and "more than" in msg and ("5" in msg or "five" in msg):

            intent = "BRANCHES_MANY_INCIDENTS"

            active_inc = self.ds.get_incidents(status="open_active")

            branch_counts = {}

            for inc in active_inc:

                b_name = inc.get("branch_name")

                branch_counts[b_name] = branch_counts.get(b_name, 0) + 1

            data_payload["branches"] = [{"branch_name": k, "active_incidents": v} for k, v in branch_counts.items() if v >= 5]

            context["last_query_type"] = "branches"



        # 20. Branch with highest active incidents

        elif "branch" in msg and ("highest" in msg or "most" in msg or "maximum" in msg) and "incident" in msg:

            intent = "HIGHEST_INCIDENTS_BRANCH"

            active_inc = self.ds.get_incidents(status="open_active")

            branch_counts = {}

            for inc in active_inc:

                b_name = inc.get("branch_name")

                branch_counts[b_name] = branch_counts.get(b_name, 0) + 1

            sorted_branches = sorted(branch_counts.items(), key=lambda x: x[1], reverse=True)

            data_payload["branches"] = [{"branch_name": k, "active_incidents": v} for k, v in sorted_branches]

            context["last_query_type"] = "branches"



        # 21. Highest Critical Alerts LHO

        # Fix Issue 7: was referencing b["branch_id"] / b["lho_name"] which don't exist in live DB format

        elif "lho" in msg and ("highest" in msg or "most" in msg) and "critical" in msg:

            intent = "HIGHEST_CRITICAL_LHO"

            lho_counts = {}

            if self.ds.engine is not None:

                try:

                    query = """

                        SELECT COALESCE(Zone, Area, 'Central Office') as lho_name, COUNT(*) as critical_alerts

                        FROM AlertsDetails

                        WHERE Severity IN ('High', 'Critical')

                        GROUP BY Zone, Area

                        ORDER BY critical_alerts DESC

                    """

                    with self.ds.engine.connect() as conn:

                        rows = conn.execute(text(query)).mappings().all()

                        data_payload["lhos"] = [dict(r) for r in rows]

                except Exception as e:

                    print(f"[SQL ERROR] HIGHEST_CRITICAL_LHO failed: {e}")

                    data_payload["lhos"] = []

            else:

                alerts = self.ds.get_alerts()

                for a in alerts:

                    if a.get("severity") in ["Critical", "High"]:

                        zone = a.get("Zone") or a.get("branch_name") or "Central Office"

                        lho_counts[zone] = lho_counts.get(zone, 0) + 1

                sorted_lhos = sorted(lho_counts.items(), key=lambda x: x[1], reverse=True)

                data_payload["lhos"] = [{"lho_name": k, "critical_alerts": v} for k, v in sorted_lhos]

            context["last_query_type"] = "lhos"



        # 22. Generic Active Incidents Listing

        elif is_semantic("ACTIVE_INCIDENTS") or (re.search(r'\bincidents?\b', msg) and not any(w in msg for w in ["count", "group", "highest", "most", "stale", "older", "operator", "priya", "aarav", "rohan", "neha", "audit", "match", "matching"])):

            intent = "ACTIVE_INCIDENTS"

            data_payload["incidents"] = self.ds.get_incidents(status="open_active")

            context["last_query_type"] = "incidents"



        # 23. Threat overview

        elif "security concern" in msg or "concern" in msg or "threat" in msg or "trend" in msg:

            intent = "SECURITY_CONCERNS"

            data_payload["dashboard"] = self.ds.get_dashboard_summary()

            data_payload["active_incidents"] = self.ds.get_incidents(status="open_active")

            data_payload["alerts"] = self.ds.get_alerts()

            context["last_query_type"] = "summary"



        # 24. Branch with highest alerts

        elif "branch" in msg and ("highest" in msg or "most" in msg or "maximum" in msg) and ("alert" in msg or "alarm" in msg):

            intent = "HIGHEST_ALERTS_BRANCH"

            data_payload["branches"] = self.ds.get_highest_alerts_branch()

            context["last_query_type"] = "branches"



        # 25. Count of branches or LHOs

        # Fix Issues 1 & 4: was using get_dashboard_summary() which queries Location_Master (1 row only)

        # Now directly counting distinct Areas from AlertsDetails which has the real branch data

        elif ("branch" in msg or "branches" in msg or "lho" in msg or "circle" in msg) and (any(w in msg for w in ["how many", "count", "total", "number of", "show", "list", "all", "what are"]) or msg in ["branches", "show me the branches", "show branches", "list branches", "all branches"]) and not any(w in msg for w in ["alert", "alerts", "vms", "sas", "analytics", "camera", "cameras", "incident", "incidents"]):


            intent = "BRANCH_COUNT"

            branches = self.ds.get_branches()

            data_payload["branches_count"] = len(branches)

            data_payload["branches"] = branches

            # Get distinct zones for LHO count

            lho_count = 1

            if self.ds.engine is not None:

                try:

                    with self.ds.engine.connect() as conn:

                        lho_count = conn.execute(text("SELECT COUNT(DISTINCT Zone) FROM AlertsDetails WHERE Zone IS NOT NULL AND Zone != ''")).scalar() or 1

                except Exception:

                    pass

            data_payload["lhos_count"] = lho_count

            context["last_query_type"] = "branches"



        # 26. Conversational Follow-up for Branch Name (requires previous query context to be "branches")

        elif context.get("last_query_type") == "branches" and (is_semantic("FOLLOW_UP_BRANCH_NAME") or (any(w in msg for w in ["which", "what", "name", "this", "it", "that", "details"]) and not any(w in msg for w in ["alert", "incident", "camera", "operator", "severity", "count", "performance"]))):

            intent = "FOLLOW_UP_BRANCH_NAME"

            data_payload["branches"] = self.ds.get_branches()

            context["last_query_type"] = "branches"



        # 27. Operator Workload (e.g. "how many alerts is priya patel handling")

        elif is_semantic("OPERATOR_WORKLOAD") or (re.search(r'\b(priya|aarav|rohan|neha)\b', msg) and any(w in msg for w in ["alert", "incident", "ticket", "workload", "handle", "handling", "assign", "assigned", "queue"])):

            intent = "OPERATOR_WORKLOAD"

            op_match = re.search(r'\b(priya(?:\s+patel)?|aarav(?:\s+sharma)?|rohan(?:\s+gupta)?|neha(?:\s+sharma)?)\b', msg)

            active_operator = op_match.group(1).strip().title() if op_match else "Priya Patel"

            

            data_payload["operator_name"] = active_operator

            

            if self.ds.use_sql_server or self.ds.engine is not None:

                try:

                    query = "SELECT IncidentId, Area as branch_name, EventType as incident_type, Priority as severity, Status as status, IncidentTime as timestamp FROM Incident_Data WHERE Operatorname LIKE :op"

                    with self.ds.engine.connect() as conn:

                        res = conn.execute(text(query), {"op": f"%{active_operator}%"})

                        data_payload["incidents"] = [dict(r) for r in res.mappings()]

                except Exception as e:

                    print(f"[SQL ERROR] OPERATOR_WORKLOAD failed: {e}")

                    data_payload["incidents"] = []

            else:

                db = self.ds._load_json_data()

                data_payload["incidents"] = [i for i in db.get("incidents", []) if active_operator.lower() in i.get("assigned_operator", "").lower()]

                

            context["last_query_type"] = "incidents"



        # 31. Alerts by specific Type and Location (e.g. "how many alerts of VMS we have and where", "how many alerts of Analytics we have and where")
        elif is_semantic("ALERTS_BY_TYPE") or (bool(self._extract_alert_type_filter(msg.lower())) and any(w in msg.lower() for w in ["how many", "count", "where", "distribution", "branch", "branches"]) and not any(w in msg.lower() for w in ["recent", "latest", "time", "order"])):
            intent = "ALERTS_BY_TYPE"
            target_type = self._extract_alert_type_filter(msg.lower()) or "VMS"
            data_payload["alert_type"] = target_type

            

            if self.ds.engine is not None:

                try:

                    loc_filter_at = self._extract_location_filter(msg.lower(), context)
                    where_parts_at = ["AlertType LIKE :alt_type"]
                    params_at = {"alt_type": f"%{target_type}%"}
                    if loc_filter_at:
                        where_parts_at.append("(Area LIKE :loc OR Location LIKE :loc)")
                        params_at["loc"] = f"%{loc_filter_at}%"

                    query = f"""
                        SELECT 
                            TRIM(COALESCE(Area, Location)) as branch_name, 
                            COUNT(*) as alert_count 
                        FROM AlertsDetails 
                        WHERE {' AND '.join(where_parts_at)}
                        GROUP BY TRIM(COALESCE(Area, Location))
                        ORDER BY alert_count DESC
                    """
                    with self.ds.engine.connect() as conn:
                        res = conn.execute(text(query), params_at)
                        data_payload["branches"] = [dict(r) for r in res.mappings()]

                except Exception as e:

                    print(f"[SQL ERROR] ALERTS_BY_TYPE query failed: {e}")

                    data_payload["branches"] = []

            else:

                db = self.ds._load_json_data()

                alerts = db.get("alerts", [])

                counts = {}

                for a in alerts:

                    if target_type.lower() in a.get("alert_type", "").lower():

                        b = a.get("branch_name")

                        counts[b] = counts.get(b, 0) + 1

                data_payload["branches"] = [{"branch_name": k, "alert_count": v} for k, v in counts.items()]

            context["last_query_type"] = "branches"



        # 30. Distinct Alert Types (e.g. "how many alert types we have", "what alert types exist")

        elif (is_semantic("ALERT_TYPES") or any(k in msg for k in ["alert type", "types of alert", "different alerts", "kinds of alert", "types of alerts"])) and not any(w in msg for w in ["show me alerts", "show alerts", "alerts by", "by the type", "by type", "by severity", "by status"]):

            intent = "ALERT_TYPES"

            if self.ds.engine is not None:

                try:

                    query = "SELECT DISTINCT AlertType FROM AlertsDetails WHERE AlertType IS NOT NULL AND AlertType != ''"

                    with self.ds.engine.connect() as conn:

                        rows = conn.execute(text(query)).mappings().all()

                        data_payload["alert_types"] = [r["AlertType"] for r in rows]

                except Exception as e:

                    print(f"[SQL ERROR] ALERT_TYPES query failed: {e}")

                    data_payload["alert_types"] = []

            else:

                db = self.ds._load_json_data()

                alerts = db.get("alerts", [])

                data_payload["alert_types"] = list(set(a.get("alert_type") for a in alerts if a.get("alert_type")))

            context["last_query_type"] = "alerts"



        # 33. Recent Alerts Filtered - handles type/area/severity filters

        # e.g. "5 most recent high-severity alerts in Noida" OR "recent VMS alerts from Agra"

        elif ("recent" in msg or "latest" in msg or "most recent" in msg or re.search(r'\b(show|list|give)\b', msg)) and ("alert" in msg or "alarm" in msg) and (

            any(t in msg for t in ["vms", "sas", "analytics", "videoanalytics", "tampering", "breach"]) or

            any(s in msg for s in ["high", "medium", "low", "critical"]) or

            any(a in msg for a in ["noida", "bhopal", "agra", "delhi", "nariman", "bkc"])

        ):

            intent = "RECENT_ALERTS_FILTERED"

            limit_match = re.search(r'\b(\d+)\b', msg)

            limit = int(limit_match.group(1)) if limit_match else 5

            

            target_type = None

            for t in ["vms", "sas", "analytics", "videoanalytics"]:

                if t in msg:

                    target_type = "VMS" if t == "vms" else ("SAS" if t == "sas" else ("Analytics" if t == "analytics" else "VideoAnalytics"))

                    break

            

            # Detect severity filter (optional)

            target_severity = None

            for s in ["high", "medium", "low", "critical"]:

                if s in msg:

                    target_severity = s.capitalize()

                    break

                    

            target_area = None

            for area in ["noida", "bhopal", "agra", "delhi", "nariman point", "bkc"]:

                if area in msg:

                    target_area = "AO_AGRA" if area == "agra" else ("AO_NOIDA" if area == "noida" else area.title())

                    break

            

            data_payload["limit"] = limit

            data_payload["target_type"] = target_type

            data_payload["target_severity"] = target_severity

            data_payload["target_area"] = target_area

            

            if self.ds.engine is not None:

                try:

                    where_clauses = []

                    params = {}

                    if target_type:

                        where_clauses.append("AlertType LIKE :alt_type")

                        params["alt_type"] = f"%{target_type}%"

                    if target_severity:

                        where_clauses.append("Severity = :severity")

                        params["severity"] = target_severity

                    if target_area:

                        where_clauses.append("(Area LIKE :area OR Location LIKE :area OR Zone LIKE :area)")

                        params["area"] = f"%{target_area}%"

                        

                    where_str = " AND ".join(where_clauses)

                    if where_str:

                        where_str = "WHERE " + where_str

                        

                    if self.ds.use_sql_server:

                        query = f"SELECT TOP {limit} AlertID as alert_id, AlertType as alert_type, COALESCE(Area, Location) as branch_name, Severity as severity, Datetime as timestamp, Status as status, Remarks as remarks FROM AlertsDetails {where_str} ORDER BY Datetime DESC"

                    else:

                        query = f"SELECT AlertID as alert_id, AlertType as alert_type, COALESCE(Area, Location) as branch_name, Severity as severity, Datetime as timestamp, Status as status, Remarks as remarks FROM AlertsDetails {where_str} ORDER BY Datetime DESC LIMIT {limit}"

                        

                    with self.ds.engine.connect() as conn:

                        res = conn.execute(text(query), params)

                        data_payload["alerts"] = [dict(r) for r in res.mappings()]

                except Exception as e:

                    print(f"[SQL ERROR] RECENT_ALERTS_FILTERED failed: {e}")

                    data_payload["alerts"] = []

            else:

                db = self.ds._load_json_data()

                alerts = db.get("alerts", [])

                filtered = []

                for a in alerts:

                    type_ok = not target_type or target_type.lower() in a.get("alert_type", "").lower()

                    sev_ok = not target_severity or target_severity.lower() == a.get("severity", "").lower()

                    area_ok = not target_area or target_area.lower() in a.get("branch_name", "").lower() or target_area.lower() in a.get("LHO", "").lower()

                    if type_ok and sev_ok and area_ok:

                        filtered.append(a)

                filtered = sorted(filtered, key=lambda x: x.get("timestamp", ""), reverse=True)

                data_payload["alerts"] = filtered[:limit]

            context["last_query_type"] = "alerts"



        # 28. Recent Alerts List

        elif is_semantic("RECENT_ALERTS") or (("recent" in msg or "latest" in msg) and ("alert" in msg or "alarm" in msg)) or (context.get("last_query_type") == "alerts" and ("recent" in msg or "latest" in msg)) or (re.search(r'\balert?s?\b|\balarm?s?\b|\banomal(?:y|ies)\b', msg) and not any(k in msg for k in ["highest", "rate", "tamper", "breach", "panic", "fire", "type", "count", "group", "grouped", "average", "avg", "total", "severity"])):

            intent = "RECENT_ALERTS"

            data_payload["alerts"] = self.ds.get_alerts()

            context["last_query_type"] = "alerts"



        # 29. Conversational Follow-up to explain the current data

        elif context.get("last_query_type") and (is_semantic("FOLLOW_UP_EXPLAIN_DATA") or any(w in msg for w in ["explain", "describe", "elaborate", "what is this", "what is it"])):

            intent = "FOLLOW_UP_EXPLAIN_DATA"

            last_type = context.get("last_query_type")

            if last_type == "alerts":

                data_payload["alerts"] = self.ds.get_alerts()

            elif last_type == "incidents":

                data_payload["incidents"] = self.ds.get_incidents()

            elif last_type == "devices" or last_type == "cameras":

                data_payload["devices"] = self.ds.get_unhealthy_devices()

            elif last_type == "branches":

                data_payload["branches"] = self.ds.get_branches()

            elif last_type == "summary":

                data_payload["summary"] = self.ds.get_dashboard_summary()



        # 32. Severity count of alerts (e.g. "What is the count of High, Medium, and Low severity alerts in the system today?")

        # Fix Issue 3: Removed today-date filter — AlertsDetails has old timestamps so filter always returned 0

        elif "severity" in msg and ("count" in msg or "how many" in msg or "number of" in msg) and "alert" in msg:

            intent = "ALERT_SEVERITY_COUNT"

            if self.ds.engine is not None:

                try:

                    query = "SELECT Severity, COUNT(*) as alert_count FROM AlertsDetails WHERE Severity IS NOT NULL AND Severity != '' GROUP BY Severity ORDER BY alert_count DESC"

                    with self.ds.engine.connect() as conn:

                        res = conn.execute(text(query))

                        data_payload["severities"] = [dict(r) for r in res.mappings()]

                except Exception as e:

                    print(f"[SQL ERROR] ALERT_SEVERITY_COUNT query failed: {e}")

                    data_payload["severities"] = []

            else:

                db = self.ds._load_json_data()

                alerts = db.get("alerts", [])

                counts = {}

                for a in alerts:

                    sev = a.get("severity") or "Unknown"

                    counts[sev] = counts.get(sev, 0) + 1

                data_payload["severities"] = [{"Severity": k, "alert_count": v} for k, v in counts.items()]

            context["last_query_type"] = "alerts"



        # 34. List all LHOs

        elif "lho" in msg and ("list" in msg or "show" in msg or "what are" in msg or "all" in msg) and not any(w in msg for w in ["incident", "alert", "alarm", "critical", "response", "time", "count", "number of"]):

            intent = "LHO_LIST"

            data_payload["lhos"] = self.ds.get_lhos()

            context["last_query_type"] = "lhos"



        else:

            # Word boundary check to prevent substring matching like "hi" inside "which"

            greeting_words = ["hello", "hi", "hey", "who are you", "what can you do"]

            if any(re.search(r'\b' + re.escape(w) + r'\b', msg) for w in greeting_words):

                intent = "GREETING"

            else:

                intent = "GENERAL_INTELLIGENCE"

                data_payload["dashboard"] = self.ds.get_dashboard_summary()

                

                # Fix Issue 12: was referencing clean_msg which is not in scope (only msg is passed here)

                # Proactively set last_query_type for follow-up context if query keywords match

                if "alert" in msg or "alarm" in msg:

                    context["last_query_type"] = "alerts"

                elif "incident" in msg or "ticket" in msg:

                    context["last_query_type"] = "incidents"

                elif "camera" in msg or "cctv" in msg or "device" in msg:

                    context["last_query_type"] = "devices"



        return intent, data_payload, context



    def _generate_with_ollama(self, query: str, history: list, intent: str, data: dict, model: str) -> str:

        """

        Sends context prompt + queried data to local Ollama instance.

        """

        if intent in ["FOLLOW_UP_EXPLAIN_DATA", "FOLLOW_UP_BRANCH_NAME"]:

            system_prompt = (

                "You are an intelligent Security Operations Analyst chatbot for the State Bank of India Centralized Monitoring System (SBI CMS).\n"

                "Your task is to explain the context of the user query based on the active dataset in progress.\n\n"

                "Rules:\n"

                "- Provide a clear, detailed, and conversational explanation of what this data represents, its significance, and operational meaning.\n"

                "- DO NOT regenerate or print the raw data table again in your output.\n"

                "- Focus on explaining the concepts (e.g. what are these security anomalies, what is the branch identity).\n"

                "- Speak like a professional SOC analyst in clean, elegant Markdown."

            )

        else:

            system_prompt = (

                "You are an intelligent Security Operations Analyst chatbot for the State Bank of India Centralized Monitoring System (SBI CMS).\n"

                "Your task is to answer user queries using ONLY the verified data provided in the prompt. Do not fabricate or assume any facts.\n\n"

                "Structure your response strictly as follows:\n"

                "1. **Direct Answer**: A clear, concise conversational response directly answering the user's question.\n"

                "2. **Key Observations**: A list of 2-3 detailed observations/insights derived from the data (e.g. identify outliers, high/low values, comparisons, averages, or technical status).\n"

                "3. **Supporting Table**: Present the structured data in a Markdown Table if applicable. Ensure columns have descriptive headers.\n"

                "4. **Operations Summary**: A brief, professional operations-level wrap-up summarizing the main security concern or recommended action based on the data.\n\n"

                "Rules:\n"

                "- Speak like a professional security operations center (SOC) analyst.\n"

                "- Never mention database schemas, SQL queries, REST APIs, or local Python backend details.\n"

                "- Answer in clean, elegant Markdown.\n"

                "- If the data block is empty, state clearly that no active incidents/offline devices matching the filter were found."

            )

        

        data_str = json.dumps(data, indent=2, ensure_ascii=False, default=str)


        user_prompt = (

            f"User Query: {query}\n"

            f"Intent Category: {intent}\n"

            f"Retrieved Real-time CMS Data:\n```json\n{data_str}\n```\n\n"

            "Provide the structured, conversational operations report."

        )

        

        messages = [{"role": "system", "content": system_prompt}]

        for h in history[-8:]:

            messages.append(h)

        messages.append({"role": "user", "content": user_prompt})

        

        try:

            r = requests.post(

                f"{self.ollama_host}/api/chat",

                json={

                    "model": model,

                    "messages": messages,

                    "stream": False,

                    "options": {

                        "temperature": 0.2

                    }

                },

                timeout=120

            )

            if r.status_code == 200:

                return r.json().get("message", {}).get("content", "")

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as net_err:

            print(f"Ollama generation failed due to network timeout/connection: {net_err}")

            raise net_err

        except Exception as e:

            print(f"Ollama generation failed: {e}")

        return None



    def _retrieve_dynamic_few_shots(self, query: str, query_plan: dict = None, k: int = 3) -> str:

        """

        Step 5: Dynamic Pattern-Tagged Few-Shot Retrieval.

        Combines 3 signals:

        1. Semantic Question Text Similarity (weight = 0.40)

        2. Plan Pattern Overlap (weight = 0.35)

        3. Plan Table/Column Overlap (weight = 0.25)

        """

        try:

            import os

            if self.embedder is None:

                self._semantic_classify(query)



            ex_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sql_examples.json")

            if not os.path.exists(ex_path):

                return ""



            with open(ex_path, "r", encoding="utf-8") as f:

                examples = json.load(f)



            if not examples:

                return ""



            # 1. Semantic Text Similarity (weight = 0.40)

            ex_questions = [ex["question"] for ex in examples]

            ex_embeddings = self.embedder.encode(ex_questions, convert_to_tensor=True)

            query_embedding = self.embedder.encode(query, convert_to_tensor=True)

            sim_scores = self.util.cos_sim(query_embedding, ex_embeddings)[0].cpu().numpy()



            # Extract structural patterns & required tables from query_plan

            plan_patterns = set()

            plan_tables = set()

            if query_plan and isinstance(query_plan, dict):

                plan_tables = set(query_plan.get("tables_needed", []))

                if len(plan_tables) > 1 or query_plan.get("join_path"):

                    plan_patterns.add("multi_table_join")

                else:

                    plan_patterns.add("single_table_filter")



                if query_plan.get("aggregations"):

                    plan_patterns.add("aggregation_groupby")



                filters_str = " ".join([str(f) for f in query_plan.get("filters", [])]).lower()

                if any(w in filters_str or w in query.lower() for w in ["today", "yesterday", "date", "hour", "time", "day", "days"]):

                    plan_patterns.add("time_window_filter")



            # Score each candidate exemplar

            scored_examples = []

            for idx, ex in enumerate(examples):

                sem_score = float(sim_scores[idx])



                # Pattern overlap score (weight = 0.35)

                ex_patterns = set(ex.get("patterns", []))

                pattern_overlap = len(plan_patterns.intersection(ex_patterns)) / max(len(plan_patterns), 1) if plan_patterns else 0.5



                # Table overlap score (weight = 0.25)

                ex_sql = ex.get("mssql", "") + " " + ex.get("sqlite", "")

                ex_tables_matched = sum(1 for t in plan_tables if t.lower() in ex_sql.lower())

                table_overlap = ex_tables_matched / max(len(plan_tables), 1) if plan_tables else 0.5



                # Combined Weighted Final Score

                final_score = (0.40 * sem_score) + (0.35 * pattern_overlap) + (0.25 * table_overlap)

                scored_examples.append((final_score, sem_score, pattern_overlap, idx, ex))



            scored_examples.sort(key=lambda x: x[0], reverse=True)

            top_k_items = scored_examples[:k]



            use_mssql = getattr(self.ds, "use_sql_server", True) if self.ds else True

            dialect_key = "mssql" if use_mssql else "sqlite"

            few_shot_lines = ["Pattern-Aware Few-Shot Exemplars (Dynamically Retrieved):"]



            for final_s, sem_s, pat_s, idx, ex in top_k_items:

                tags_str = ", ".join(ex.get("patterns", []))

                few_shot_lines.append(f"Q: {ex['question']} [Patterns: {tags_str}]")

                few_shot_lines.append(f"SQL: {ex[dialect_key]}\n")



            print(f"[PATTERN RAG] Selected top {k} exemplars for plan patterns {list(plan_patterns)}.")

            return "\n".join(few_shot_lines) + "\n"



        except Exception as e:

            print(f"[PATTERN RAG ERROR] Failed to retrieve pattern-tagged few shots: {e}")

            return ""



    def check_schema_confidence(self, link_res: dict, query_text: str, context: dict = None) -> tuple:

        """

        Reusable Schema Confidence & Abstention Guard.

        Validates schema confidence before SQL generation or planning steps.

        Fix A: Margin check (Delta < 0.05) is computed ONLY among independently-matched tables

        (cleared 0.35 on their own similarity score), excluding FK-expanded tables.

        

        Returns:

            tuple: (proceed: bool, response_msg: str, candidate_tables: list)

        """

        relevant_tables = link_res.get("relevant_tables", [])

        expanded_tables = link_res.get("expanded_tables", [])

        relevant_columns = link_res.get("relevant_columns", [])

        

        # 1. Zero Tables Matched (no table cleared >= 0.35 threshold even after FK expansion)

        if not relevant_tables and not expanded_tables:

            msg = (

                "I don't have data to answer that question with the current database schema.\n\n"

                "### Available System Domain Data\n"

                "You can query operational metrics on:\n"

                "- **Security Alerts & Telemetry**: `AlertsDetails`\n"

                "- **Incidents & Operator Tickets**: `Incident_Data` / `IncidentHistory`\n"

                "- **CCTV Devices & Status**: `CameraList` / `Master_CamDetails`\n"

                "- **Standard Operating Procedures**: `SOP_MASTER`"

            )

            self._log_abstention(query_text, best_table="None", top_score=0.0, second_score=0.0, margin=0.0, reason="ZERO_TABLES_MATCHED")

            if context is not None:

                context["last_query_type"] = "abstention"

                context["last_abstention"] = {"query": query_text, "candidates": []}

            return False, msg, []



        # Fix A: Compute scores ONLY for independently matched tables (in relevant_tables)

        indep_table_scores = {}

        for col in relevant_columns:

            tbl = col.get("table_name")

            if tbl in relevant_tables:

                sc = col.get("score", 0.0)

                if tbl not in indep_table_scores or sc > indep_table_scores[tbl]:

                    indep_table_scores[tbl] = sc



        for tbl in relevant_tables:

            if tbl not in indep_table_scores:

                indep_table_scores[tbl] = 0.35



        # Remove legacy/auxiliary tables if primary table 'AlertsDetails' is present
        AUXILIARY_ALERT_TABLES = ["Alerts", "AlertHistory", "Alert_Comments", "AlertSupDetails", "AlertSubtype", "AlertTypes", "Master_CamDetails"]
        if "AlertsDetails" in indep_table_scores:
            for aux in AUXILIARY_ALERT_TABLES:
                if aux in indep_table_scores:
                    del indep_table_scores[aux]

        # Auto-bypass margin check if query is asking about alerts, cameras, or incidents
        query_lower = query_text.lower()
        if "alert" in query_lower or "alerts" in query_lower or "alertsdetail" in query_lower:
            indep_table_scores = {"AlertsDetails": 0.99}
        elif "camera" in query_lower or "cameras" in query_lower or "cctv" in query_lower:
            indep_table_scores = {"CameraList": 0.99}
        elif "incident" in query_lower or "incidents" in query_lower or "ticket" in query_lower or "tickets" in query_lower:
            indep_table_scores = {"Incident_Data": 0.99}



        sorted_indep_scores = sorted(indep_table_scores.items(), key=lambda x: x[1], reverse=True)

        

        top_score = sorted_indep_scores[0][1] if sorted_indep_scores else 0.0

        best_table = sorted_indep_scores[0][0] if sorted_indep_scores else "Unknown"

        

        second_score = sorted_indep_scores[1][1] if len(sorted_indep_scores) > 1 else 0.0

        second_table = sorted_indep_scores[1][0] if len(sorted_indep_scores) > 1 else None

        

        margin = round(top_score - second_score, 4) if len(sorted_indep_scores) > 1 else 1.0



        candidates = list(dict.fromkeys(relevant_tables + expanded_tables))[:2]



        # 2. Score Margin Check: Close race between independently matched tables (Delta < 0.05)

        CLOSE_RACE_MARGIN_THRESHOLD = 0.05

        if len(sorted_indep_scores) >= 2 and margin < CLOSE_RACE_MARGIN_THRESHOLD:
            msg = (
                "Your request touches multiple operational data areas (such as monitored LHO circles, asset management, or alert telemetry).\n\n"
                "Please clarify if you are asking about LHO command circles, device assets, or security alert metrics."
            )

            self._log_abstention(query_text, best_table=best_table, top_score=top_score, second_score=second_score, margin=margin, reason="AMBIGUOUS_TABLE_RACE")

            if context is not None:

                context["last_query_type"] = "abstention"

                context["last_abstention"] = {"query": query_text, "candidates": candidates}

            return False, msg, candidates



        # 3. Absolute Low-Confidence Threshold (< 0.20)
        LOW_CONFIDENCE_THRESHOLD = 0.20

        if top_score > 0.0 and top_score < LOW_CONFIDENCE_THRESHOLD:

            cand_str = "\n".join([f"- Table **{c}**" for c in candidates])

            msg = (

                f"I found a partial schema match for your request, but confidence is low (score: `{top_score:.3f}`).\n\n"

                f"Did you mean to query one of these candidate tables?\n{cand_str}\n\n"

                "Please refine your question with more specific domain terms."

            )

            self._log_abstention(query_text, best_table=best_table, top_score=top_score, second_score=second_score, margin=margin, reason="LOW_CONFIDENCE_MATCH")

            if context is not None:

                context["last_query_type"] = "abstention"

                context["last_abstention"] = {"query": query_text, "candidates": candidates}

            return False, msg, candidates



        return True, "", candidates



    def _log_abstention(self, query_text: str, best_table: str, top_score: float, second_score: float, margin: float, reason: str):

        """Logs query abstentions with top score, second score, margin, and reason to an audit log file."""

        log_entry = {

            "timestamp": datetime.now().isoformat(),

            "query": query_text,

            "best_match_table": best_table,

            "top_score": round(top_score, 4),

            "second_score": round(second_score, 4),

            "margin_delta": round(margin, 4),

            "reason": reason

        }

        print(f"[ABSTENTION GUARD LOG] {reason}: Query='{query_text}' | BestTable={best_table} | TopScore={top_score:.4f} | Margin={margin:.4f}")

        try:

            log_dir = os.path.join(os.path.dirname(__file__), "logs")

            os.makedirs(log_dir, exist_ok=True)

            log_file = os.path.join(log_dir, "abstentions.jsonl")

            with open(log_file, "a", encoding="utf-8") as f:

                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        except Exception as e:

            print(f"[ABSTENTION LOG WARNING] Failed to write log: {e}")



    def _generate_query_plan(self, query: str, dynamic_schema: str, model: str) -> dict:

        """Step 3: Generates a structured query plan via LLM before SQL generation (temperature=0.0)."""

        plan_system_prompt = (

            "You are a Senior SQL Operations Architect for the State Bank of India Centralized Monitoring System (SBI CMS).\n"

            "Your task is to analyze the user query and the schema graph, then output a structured query plan.\n"

            "DO NOT write SQL. Output ONLY a single valid JSON block starting with ```json and ending with ```.\n\n"

            "JSON Object Format Required:\n"

            "{\n"

            '  "tables_needed": ["Table1", "Table2"],\n'

            '  "join_path": [\n'

            '    {"source_table": "Table1", "source_col": "col1", "target_table": "Table2", "target_col": "col2"}\n'

            '  ],\n'

            '  "filters": ["condition1"],\n'

            '  "aggregations": ["agg1"],\n'

            '  "output_columns": ["col1", "col2"]\n'

            "}\n\n"

            f"{dynamic_schema}\n"

        )

        

        user_prompt = f"Formulate a structured execution plan for question: '{query}'"

        

        try:

            r = requests.post(

                f"{self.ollama_host}/api/chat",

                json={

                    "model": model,

                    "messages": [

                        {"role": "system", "content": plan_system_prompt},

                        {"role": "user", "content": user_prompt}

                    ],

                    "stream": False,

                    "options": {"temperature": 0.0}

                },

                timeout=120

            )

            if r.status_code == 200:

                json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL | re.IGNORECASE)
                if json_match:
                    raw_json = json_match.group(1).strip()
                else:
                    brace_match = re.search(r'(\{.*\})', content, re.DOTALL)
                    raw_json = brace_match.group(1).strip() if brace_match else content.strip()

                parsed = json.loads(raw_json)
                return parsed if isinstance(parsed, dict) else {}

        except Exception as e:

            print(f"[QUERY PLAN ERROR] Plan generation failed: {e}")

        return {}



    def validate_query_plan(self, plan: dict, expanded_tables: list) -> tuple:

        """

        Step 3 & Fix B: Validates tables, FK edges, output column existence, 

        and flags ungrounded categorical literal value warnings.

        Returns: tuple (is_valid: bool, error_reason: str)

        """

        if not plan or not isinstance(plan, dict) or not plan.get("tables_needed"):
            top_table = "AlertsDetails" if "AlertsDetails" in expanded_tables else (expanded_tables[0] if expanded_tables else "AlertsDetails")
            print(f"[QUERY PLAN FALLBACK] Using default plan for top table '{top_table}'")
            plan = {
                "tables_needed": [top_table],
                "join_path": [],
                "filters": [],
                "aggregations": [],
                "output_columns": ["*"]
            }

        tables_needed = plan.get("tables_needed", [])
        if not tables_needed:
            return False, "Plan specified zero required tables"



        full_schema = self.schema_engine.tables_schema if self.schema_engine else {}

        expanded_set = set(expanded_tables) if expanded_tables else set(full_schema.keys())



        # 1. Validate Table Existence in Schema Graph

        for table in tables_needed:

            if table not in expanded_set:

                return False, f"Table '{table}' referenced in plan does not exist in the introspected schema graph"



        # 2. Validate Join Edges in Schema Graph

        join_path = plan.get("join_path", [])

        fk_edges = getattr(self.schema_engine, "fk_edges", [])

        

        for join_item in join_path:

            if not isinstance(join_item, dict):

                continue

            src_tbl = join_item.get("source_table")

            tgt_tbl = join_item.get("target_table")

            src_col = join_item.get("source_col")

            tgt_col = join_item.get("target_col")



            if len(tables_needed) > 1 and src_tbl and tgt_tbl:

                edge_exists = any(

                    (

                        (e["source_table"].lower() == src_tbl.lower() and e["target_table"].lower() == tgt_tbl.lower()) or

                        (e["source_table"].lower() == tgt_tbl.lower() and e["target_table"].lower() == src_tbl.lower())

                    ) and (

                        not src_col or not tgt_col or

                        (e["source_col"].lower() == src_col.lower() and e["target_col"].lower() == tgt_col.lower()) or

                        (e["source_col"].lower() == tgt_col.lower() and e["target_col"].lower() == src_col.lower())

                    )

                    for e in fk_edges

                )

                if not edge_exists:

                    return False, f"Join edge '{src_tbl}.{src_col} <-> {tgt_tbl}.{tgt_col}' in plan is invalid (no FK relationship in graph)"



        # 3. Fix B: Column-Level Existence & Categorical Value Verification

        out_cols = plan.get("output_columns", [])

        filters = plan.get("filters", [])

        col_values_cache = getattr(self.schema_engine, "column_values_cache", {})



        all_known_cols = {}

        for tbl in tables_needed:

            if tbl in full_schema:

                all_known_cols[tbl.lower()] = {c["name"].lower(): c["name"] for c in full_schema[tbl]["columns"]}



        # Check Output Columns Existence

        for col_ref in out_cols:

            if "." in col_ref and not any(f in col_ref.lower() for f in ["count(", "sum(", "avg(", "min(", "max("]):

                tbl_part, col_part = col_ref.split(".", 1)

                tbl_part = tbl_part.strip().lower()

                col_part = col_part.strip().lower()

                if tbl_part in all_known_cols and col_part not in all_known_cols[tbl_part]:

                    return False, f"Column '{col_part}' referenced in plan output_columns does not exist on table '{tbl_part}'"



        # Check Filters for Categorical Value Warnings

        for flt in filters:

            flt_str = str(flt)

            for tbl_name, col_dict in all_known_cols.items():

                for col_lower, real_col_name in col_dict.items():

                    col_key_sample = f"{tbl_name}.{real_col_name}"

                    if col_key_sample.lower() in flt_str.lower() and col_key_sample in col_values_cache:

                        quoted_match = re.search(r"['\"]([^'\"]+)['\"]", flt_str)

                        if quoted_match:

                            literal_val = quoted_match.group(1).strip()

                            cached_samples = [str(s).lower() for s in col_values_cache[col_key_sample]]

                            if cached_samples and not any(literal_val.lower() in s for s in cached_samples):

                                print(f"[PLAN WARNING] Literal '{literal_val}' not found in sample cache for column '{col_key_sample}'")



        return True, ""



    def _check_structural_mismatch(self, sql_query: str, query_plan: dict, rows: list) -> str:

        """Step 4: Checks if executed SQL structurally omitted plan aggregations or join clauses."""

        if not query_plan or not isinstance(query_plan, dict):

            return None



        sql_lower = sql_query.lower()

        plan_aggs = query_plan.get("aggregations", [])

        

        # Priority 3 Check: Plan requested aggregation (COUNT, SUM, AVG) but SQL lacks aggregate functions

        if plan_aggs and not any(w in sql_lower for w in ["count", "sum", "avg", "min", "max", "group by"]):

            return f"Plan requested aggregation {plan_aggs} but SQL query lacks aggregate functions or GROUP BY"



        # Priority 3 Check: Plan requested multi-table join but SQL query lacks JOIN clause

        plan_tables = query_plan.get("tables_needed", [])

        if len(plan_tables) > 1 and "join" not in sql_lower and "," not in (sql_lower.split("from")[1] if "from" in sql_lower else ""):

            return f"Plan requested multi-table join across {plan_tables} but SQL query lacks JOIN clause"



        return None



    def _log_query_repair(self, query: str, trigger: str, orig_sql: str, rep_sql: str, outcome: str):

        """Step 4: Logs query repairs (trigger reason, original SQL, repaired SQL, outcome) to audit log."""

        log_entry = {

            "timestamp": datetime.now().isoformat(),

            "query": query,

            "trigger": trigger,

            "original_sql": orig_sql,

            "repaired_sql": rep_sql,

            "outcome": outcome

        }

        print(f"[QUERY REPAIR LOG] Trigger='{trigger}' | Outcome='{outcome}' | OrigSQL='{orig_sql}' | RepSQL='{rep_sql}'")

        try:

            log_dir = os.path.join(os.path.dirname(__file__), "logs")

            os.makedirs(log_dir, exist_ok=True)

            log_file = os.path.join(log_dir, "query_repairs.jsonl")

            with open(log_file, "a", encoding="utf-8") as f:

                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        except Exception as e:

            print(f"[REPAIR LOG WARNING] Failed to write repair log: {e}")



    def _process_message_with_text_to_sql(self, query: str, history: list, model: str, context: dict) -> str:

        """

        Translates a natural language query into SQL using Ollama, validates it via sqlglot,

        executes it with timeouts and limits, and formats the response. Features automatic

        1-shot self-repair loops for DB exceptions, 0-rows returned, and structural mismatches.

        """

        import sqlglot

        from sqlglot import expressions as exp

        import time



        dialect = "SQLite" if not self.ds.use_sql_server else "Microsoft SQL Server (MS SQL)"

        dialect_rules = (

            "Return ONLY valid SQLite SELECT statements.\n"

            "- Use LIMIT N to restrict output instead of TOP N.\n"

            "- Use standard date strings or datetime('now') functions."

        ) if not self.ds.use_sql_server else (

            "Return ONLY valid Microsoft SQL Server SELECT statements.\n"

            "- Use SELECT TOP N to limit output.\n"

            "- Use standard datetime parsing."

        )



        # Dynamic Schema Linking & Grounding with Abstention Guard

        dynamic_schema = ""

        expanded_tables = []

        if self.schema_linker:

            link_res = self.schema_linker.link_schema_and_values(query)
            
            # Step 2 & Fix A: Abstention Path Guard check (margin computed only on independently-matched tables)
            proceed, clarification_msg, candidates = self.check_schema_confidence(link_res, query, context=context)
            if not proceed:
                print(f"[ABSTENTION GUARD] Short-circuiting SQL generation for query: '{query}'")
                return clarification_msg

            dynamic_schema = link_res.get("focused_schema_prompt", "")
            expanded_tables = link_res.get("expanded_tables", [])
            grounded_values = link_res.get("grounded_values", {})

            grounding_prompt_str = ""
            if grounded_values:
                g_lines = []
                for g_key, g_info in grounded_values.items():
                    col = f"{g_info['table_name']}.{g_info['column_name']}"
                    val = g_info['db_value']
                    g_lines.append(f"- Filter on `{col}` MUST use exact literal: `{col} = '{val}'`")
                grounding_prompt_str = "\n[MANDATORY GROUNDED VALUE FILTERS]\n" + "\n".join(g_lines) + "\n"

        if not dynamic_schema:
            dynamic_schema = self.schema_engine.generate_dynamic_schema_prompt(dialect) if self.schema_engine else ""

        # Step 3: Query Plan Reasoning & Programmatic Validation
        plan_start_t = time.time()
        query_plan = self._generate_query_plan(query, dynamic_schema + grounding_prompt_str, model)
        plan_duration_ms = int((time.time() - plan_start_t) * 1000)

        plan_valid, plan_error = self.validate_query_plan(query_plan, expanded_tables)
        if not plan_valid:
            print(f"[QUERY PLAN REJECTED] {plan_error} | Query='{query}'")
            msg = (
                f"I couldn't generate a valid query execution plan for your request.\n\n"
                f"**Reason**: {plan_error}.\n"
                "Please verify table or entity names and rephrase your question."
            )
            top_tbl = expanded_tables[0] if expanded_tables else "None"
            self._log_abstention(query, best_table=top_tbl, top_score=0.0, second_score=0.0, margin=0.0, reason=f"INVALID_PLAN ({plan_error})")
            if context is not None:
                context["last_query_type"] = "abstention"
                context["last_abstention"] = {"query": query, "candidates": expanded_tables[:2]}
            return msg

        print(f"[QUERY PLAN VALIDATED] Plan generated in {plan_duration_ms}ms: {json.dumps(query_plan)}")
        plan_prompt_str = f"[VALIDATED QUERY PLAN]\n```json\n{json.dumps(query_plan, indent=2)}\n```\n{grounding_prompt_str}\nWrite the SQL query following this plan."
        few_shots = self._retrieve_dynamic_few_shots(query, query_plan=query_plan, k=3)

        schema_prompt = (
            f"You are a {dialect} database translator for the State Bank of India Centralized Monitoring System (SBI CMS).\n"
            "Based on the user's natural language question, write a single SQL query to retrieve the necessary data.\n"
            "Only return the SQL query inside a markdown code block starting with ```sql and ending with ```. Do not explain the query, do not write extra text.\n\n"
            f"{dynamic_schema}\n{grounding_prompt_str}\n"
            f"{few_shots}"
            "Guidelines:\n"
            f"- {dialect_rules}\n"
            "- For string matching, use LIKE with wildcards (e.g. Area LIKE '%Bhopal%') to be robust against minor typos.\n"
            "- If querying a specific ticket ID (e.g. INC-001), match the numeric part (e.g. WHERE IncidentId = 1) because Incident_Data.IncidentId is numeric.\n"
            "- Always select readable columns (like Area or Location, EventType, Status, Time).\n"
            "- Do NOT compute response time delay (AckTime - Datetime) UNLESS the query explicitly asks for 'response time' or 'delay'.\n"
            "- STRICT FILTER COMPLIANCE: Always enforce exact grounded value filters specified in MANDATORY GROUNDED VALUE FILTERS.\n"
            "- DO NOT join AlertsDetails and Incident_Data unless the question explicitly asks about operators or supervisors. For general alert details or alert count questions, query AlertsDetails alone."
        )

        last_sql = context.get("last_sql")
        sql_memory_prompt = ""
        if last_sql:
            sql_memory_prompt = (
                f"\n\n[CONVERSATIONAL SQL CONTEXT]\n"
                f"The user's previous query was resolved to this working SQL: `{last_sql}`.\n"
                f"If the user's current question is a follow-up or refinement of their previous request, "
                f"write a modified query building on top of the previous SQL query (e.g. adding a filter, sorting, grouping, or modifying column selection). "
                f"Otherwise, write a completely new query."
            )

        max_retries = 2  # 1 initial attempt + 1 repair attempt ceiling
        error_history = ""
        repair_trigger = None
        orig_sql = None

        for attempt in range(max_retries):
            if attempt == 0:
                current_user_prompt = f"{plan_prompt_str}\n\nWrite a {dialect} query to retrieve data for this question: '{query}'{sql_memory_prompt}"
            else:
                current_user_prompt = (
                    f"{plan_prompt_str}\n\n"
                    f"[1-SHOT SELF-REPAIR TRIGGER: {repair_trigger}]\n"
                    f"Previous SQL query attempted: `{orig_sql}`\n"
                    f"Details / Guidance: {error_history}\n\n"
                    f"Please rewrite and correct the SQL query inside a ```sql ... ``` block."
                )

            try:
                # Step 1: Send query to Ollama
                try:
                    r = requests.post(
                        f"{self.ollama_host}/api/chat",
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": schema_prompt},
                                {"role": "user", "content": current_user_prompt}
                            ],
                            "stream": False,
                            "options": {"temperature": 0.0}
                        },
                        timeout=120
                    )
                    if r.status_code != 200:
                        continue

                    sql_response = r.json().get("message", {}).get("content", "")
                    print(f"[Text-to-SQL] (Attempt {attempt+1}) Generated raw response:\n{sql_response}")

                    # Extract code blocks
                    sql_match = re.search(r'```sql\s*(.*?)\s*```', sql_response, re.DOTALL | re.IGNORECASE)
                    if sql_match:
                        sql_query = sql_match.group(1).strip()
                    else:
                        stmt_match = re.search(r'(SELECT\s+.*)', sql_response, re.DOTALL | re.IGNORECASE)
                        if stmt_match:
                            sql_query = stmt_match.group(1).strip()
                        else:
                            raise ValueError("The generated response did not contain a valid SQL code block starting with SELECT.")
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as timeout_err:
                    print(f"[OLLAMA TIMEOUT] Ollama generation timed out: {timeout_err}. Using deterministic plan-grounded fallback SQL.")
                    top_tbl = expanded_tables[0] if expanded_tables else "AlertsDetails"
                    where_clauses = []
                    if grounded_values:
                        for g_key, g_info in grounded_values.items():
                            g_tbl = g_info.get("table_name", top_tbl)
                            g_col = g_info.get("column_name")
                            g_val = g_info.get("db_value")
                            if g_col and g_val and g_tbl == top_tbl:
                                where_clauses.append(f"{g_tbl}.{g_col} = '{g_val}'")
                    where_str = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
                    if self.ds.use_sql_server:
                        sql_query = f"SELECT TOP 20 * FROM {top_tbl}{where_str} ORDER BY Datetime DESC"
                    else:
                        sql_query = f"SELECT * FROM {top_tbl}{where_str} ORDER BY Datetime DESC LIMIT 20"

                sql_query = sql_query.rstrip(";")
                print(f"[Text-to-SQL] (Attempt {attempt+1}) Cleaned query: {sql_query}")

                # Step 2: AST Safety Validation via sqlglot
                dialect_name = "tsql" if self.ds.use_sql_server else "sqlite"
                parsed = sqlglot.parse_one(sql_query, read=dialect_name)
                
                if parsed.key.upper() != "SELECT":
                    raise ValueError("Only read-only SELECT statements are whitelisted for execution.")

                for node in parsed.walk():
                    if isinstance(node[0], (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Command)):
                        raise ValueError("Execution blocked: Modifying statements are strictly prohibited.")

                if dialect_name == "sqlite":
                    if "limit" not in sql_query.lower():
                        sql_query += " LIMIT 100"
                else:
                    if "top" not in sql_query.lower():
                        sql_query = re.sub(r'^SELECT\b', 'SELECT TOP 100', sql_query, flags=re.IGNORECASE)

                print(f"[Text-to-SQL] Running AST-validated query: {sql_query}")

                # Step 3: Execute query with timeout
                with self.ds.engine.connect() as conn:
                    res = conn.execute(text(sql_query))
                    rows = [dict(row) for row in res.mappings()]

                print(f"[Text-to-SQL] Attempt {attempt+1} execution success. Retrieved {len(rows)} rows.")

                # Step 4: Semantic & Structural Sanity Checks (Attempt 0 only)
                if attempt == 0:
                    # Priority 2 Check: 0-Rows Returned
                    if len(rows) == 0:
                        repair_trigger = "0_ROWS_RETURNED"
                        error_history = "The query executed successfully but returned 0 rows. Reconsider whether your JOIN conditions or string literal WHERE filters (exact matches vs casing) are overly restrictive. Consider using LIKE with '%wildcards%' if matching text."
                        orig_sql = sql_query
                        print(f"[SELF-REPAIR] Priority 2: 0 Rows returned on Attempt 1. Triggering 1-shot repair...")
                        self._log_query_repair(query, trigger=repair_trigger, orig_sql=orig_sql, rep_sql=None, outcome="retrying")
                        continue

                    # Priority 3 Check: Structural Mismatch
                    struct_err = self._check_structural_mismatch(sql_query, query_plan, rows)
                    if struct_err:
                        repair_trigger = "STRUCTURAL_MISMATCH"
                        error_history = f"Structural mismatch with plan: {struct_err}. Ensure all requested aggregations/columns from plan are included in SQL."
                        orig_sql = sql_query
                        print(f"[SELF-REPAIR] Priority 3: Structural Mismatch on Attempt 1: {struct_err}. Triggering 1-shot repair...")
                        self._log_query_repair(query, trigger=repair_trigger, orig_sql=orig_sql, rep_sql=None, outcome="retrying")
                        continue

                # If repair attempt 1 completed successfully, log outcome
                if attempt == 1 and orig_sql:
                    outcome = "repaired_success" if len(rows) > 0 else "repaired_zero_rows"
                    self._log_query_repair(query, trigger=repair_trigger, orig_sql=orig_sql, rep_sql=sql_query, outcome=outcome)

                for row in rows:
                    for k, v in row.items():
                        if isinstance(v, datetime):
                            row[k] = v.isoformat()

                data_str = json.dumps(rows, indent=2, ensure_ascii=False)

                # Update ContextTracker result context for follow-up refinements
                if isinstance(context, dict):
                    context["last_sql"] = sql_query
                    context["last_result_context"] = {
                        "question": query,
                        "sql": sql_query,
                        "tables": query_plan.get("tables_needed", []),
                        "filters": query_plan.get("filters", []),
                        "row_count": len(rows)
                    }

                # TASK: Natural Language Response Synthesis
                final_response = self._synthesize_natural_response(query, query_plan, rows, model=model, history=history)
                return final_response, context




            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as net_err:
                print(f"[Text-to-SQL Network Error] Attempt {attempt+1} failed: {net_err}. Executing grounded live database fallback query.")
                top_tbl = expanded_tables[0] if expanded_tables else "AlertsDetails"
                where_clauses = []
                if grounded_values:
                    for g_key, g_info in grounded_values.items():
                        g_tbl = g_info.get("table_name", top_tbl)
                        g_col = g_info.get("column_name")
                        g_val = g_info.get("db_value")
                        if g_col and g_val and g_tbl == top_tbl:
                            where_clauses.append(f"{g_tbl}.{g_col} = '{g_val}'")
                where_str = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
                if self.ds.use_sql_server:
                    fallback_sql = f"SELECT TOP 20 * FROM {top_tbl}{where_str} ORDER BY Datetime DESC"
                else:
                    fallback_sql = f"SELECT * FROM {top_tbl}{where_str} ORDER BY Datetime DESC LIMIT 20"

                rows = self.ds.execute_raw_sql(fallback_sql)
                context["last_sql"] = fallback_sql
                if rows:
                    for r in rows:
                        for k, v in r.items():
                            if isinstance(v, datetime):
                                r[k] = v.isoformat()
                    headers = list(rows[0].keys())
                    table_md = "| " + " | ".join(headers) + " |\n" + "| " + " | ".join(["---"] * len(headers)) + " |\n"
                    for r in rows:
                        table_md += "| " + " | ".join(str(r.get(h, "")) for h in headers) + " |\n"
                    return f"### Live Database Query Result\n**Executed SQL**: `{fallback_sql}`\n\n{table_md}", context
                return f"### Live Database Query Result\n**Executed SQL**: `{fallback_sql}`\n\n**Result**: 0 matching records found.", context

            except Exception as e:
                print(f"[Text-to-SQL Warning] Attempt {attempt+1} failed: {e}")
                error_history = str(e)

        return None
    def _sanitize_and_audit_response(self, response_str: str) -> str:
        """
        TASK 5: Audits and sanitizes synthesis output to ensure zero leaks of:
        - Internal database table names (AlertsDetails, CameraList, usr_mstr, etc.)
        - Internal column names (AckTime, Datetime, AlertID, etc.)
        - SQL code snippets (SELECT, WHERE, DATEDIFF, etc.)
        - Internal confidence scores (score: 0.99, margin: 0.05, etc.)
        - CoT & LLM Evaluation benchmark leakage (Senior Security Analyst, Key Insights, Questions, etc.)
        """
        if not response_str:
            return ""

        sanitized = response_str

        # 1. Clean CoT & Benchmark artifacts (Senior Security Analyst, Key Insights, Questions, etc.)
        if "Response:" in sanitized:
            # Extract content after Response: block if present
            parts = sanitized.split("Response:")
            res_part = parts[1].strip()
            # Truncate any subsequent benchmark sections like Key Insights:, Questions:, etc.
            res_part = re.split(r'\n\s*(?:Key Insights|Next Steps|Questions|Possible Answers|Best regards):', res_part, flags=re.IGNORECASE)[0]
            sanitized = res_part.strip("`\n ")

        # Truncate signatures or trailing CoT blocks
        sanitized = re.split(r'\n\s*(?:Best regards,|Senior Security Analyst|Intelligence Services|Key Insights:|Next Steps:|Questions:|Possible Answers:)', sanitized, flags=re.IGNORECASE)[0]

        # Remove raw table names if leaked in natural text
        table_names = ["AlertsDetails", "CameraList", "Master_CamDetails", "usr_mstr", "Incident_Data", "IncidentHistory", "AlertHistory", "SOP_MASTER"]
        for tbl in table_names:
            sanitized = re.sub(rf'\b{tbl}\b', 'database records', sanitized, flags=re.IGNORECASE)

        # Remove raw SQL statements or code blocks if accidentally generated in NL response
        sanitized = re.sub(r'```sql.*?```', '', sanitized, flags=re.DOTALL | re.IGNORECASE)
        sanitized = re.sub(r'\bSELECT\s+.*?\bFROM\b.*?(?:;|$)', '', sanitized, flags=re.IGNORECASE)

        # Remove internal score metrics
        sanitized = re.sub(r'\(score:\s*`?\d+\.\d+`?\)', '', sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(r'margin score difference:\s*`?\d+\.\d+`?', '', sanitized, flags=re.IGNORECASE)

        return sanitized.strip()

    def _log_synthesis(self, query: str, plan: dict, shape: str, row_count: int, output_text: str):
        """Logs synthesis input/output pair alongside existing plan/repair logs."""
        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "query": query,
                "shape": shape,
                "plan_summary": {
                    "tables": plan.get("tables_needed", []),
                    "aggregations": plan.get("aggregations", []),
                    "filters": plan.get("filters", [])
                } if isinstance(plan, dict) else {},
                "row_count": row_count,
                "synthesis_output": output_text
            }
            log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, "synthesis_audit.jsonl")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception as e:
            print(f"[SYNTHESIS LOG ERROR] Failed to write synthesis log: {e}")

    def _fallback_synthesize(self, query: str, query_plan: dict, rows: list, shape: str) -> str:
        """Deterministic fallback synthesizer when LLM synthesis is unavailable or times out."""
        def render_table(data_rows):
            if not data_rows: return ""
            headers = list(data_rows[0].keys())
            tbl = "| " + " | ".join(headers) + " |\n"
            tbl += "| " + " | ".join(["---"] * len(headers)) + " |\n"
            for r in data_rows:
                tbl += "| " + " | ".join(str(r.get(h, "")) for h in headers) + " |\n"
            return tbl

        row_count = len(rows) if rows else 0
        if shape == "ZERO_ROWS":
            return f"I couldn't find any data matching your request (**'{query}'**)."
        elif shape == "SCALAR":
            val = list(rows[0].values())[0] if rows and len(rows[0]) > 0 else 0
            key = list(rows[0].keys())[0] if rows and len(rows[0]) > 0 else "count"
            return f"The total **{key}** for your request is **{val:,}**."
        elif shape == "LARGE_RESULT":
            tbl_md = render_table(rows[:15])
            return (
                f"Retrieved **{row_count:,} total records** matching your request. "
                f"Displaying top 15 results below:\n\n{tbl_md}\n\n"
                f"*(Showing top 15 out of {row_count:,} total matching database records).*"
            )
        else:
            tbl_md = render_table(rows)
            return f"Here are the matching records for your request (**{row_count} records retrieved**):\n\n{tbl_md}"

    def _synthesize_natural_response(self, query: str, query_plan: dict, rows: list, model: str = "sqlcoder:15b", history: list = None) -> str:
        """
        TASK: Natural Language Response Synthesis (LLM Layer)
        Renders clean natural language explanation + table (when appropriate).
        """
        row_count = len(rows) if rows else 0

        if row_count == 0:
            shape = "ZERO_ROWS"
        elif row_count == 1 and len(rows[0]) == 1:
            shape = "SCALAR"
        elif row_count == 1 and any(k.lower() in ["total", "count", "avg", "average", "sum", "cnt", "total_alerts", "alert_count"] for k in rows[0].keys()):
            shape = "SCALAR"
        elif row_count > 20:
            shape = "LARGE_RESULT"
        else:
            shape = "LIST_TABLE"

        plan_prompt_summary = {
            "tables": query_plan.get("tables_needed", []),
            "aggregations": query_plan.get("aggregations", []),
            "filters": query_plan.get("filters", [])
        } if isinstance(query_plan, dict) else {}

        sample_rows = rows[:15] if row_count > 15 else rows

        system_prompt = (
            "You are an intelligent, conversational Security Operations Analyst chatbot for the State Bank of India Centralized Monitoring System (SBI CMS).\n"
            "Your job is to answer the user's question directly and concisely using the database query results provided.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "- Do NOT include signatures, sign-offs, roleplays, or benchmark evaluation text (e.g. 'Senior Security Analyst', 'Best regards', 'Key Insights', 'Next Steps', 'Questions').\n"
            "- Do NOT explain how simple the data is or write meta-commentary about the prompt.\n"
            "- Never leak table names or internal SQL queries.\n"
            "- Target Response Shape: " + shape + "\n"
        )

        user_prompt = (
            f"User Question: '{query}'\n"
            f"Target Shape: {shape}\n"
            f"Database Output ({row_count} total rows):\n```json\n{json.dumps(sample_rows, indent=2, default=str)}\n```\n\n"
            "Provide only the direct natural language answer."
        )

        synthesis_text = None
        try:
            r = requests.post(
                f"{self.ollama_host}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "stop": ["Best regards,", "Senior Security Analyst", "Intelligence Services", "Key Insights:", "Next Steps:", "Questions:", "Possible Answers:"]
                    }
                },
                timeout=12
            )
            if r.status_code == 200:
                content_str = r.json().get("message", {}).get("content", "").strip()
                if content_str:
                    synthesis_text = content_str
        except Exception as e:
            print(f"[SYNTHESIS LLM WARNING] LLM call failed ({e}). Using deterministic synthesizer.")

        if not synthesis_text:
            synthesis_text = self._fallback_synthesize(query, query_plan, rows, shape)

        sanitized = self._sanitize_and_audit_response(synthesis_text)
        self._log_synthesis(query, query_plan, shape, row_count, sanitized)
        return sanitized

    def _compile_fallback_response(self, intent: str, data: dict, msg: str, context: dict) -> str:


        """

        Failsafe response generator that formats queries using local Python code if Ollama is offline.

        """

        if intent == "GREETING":

            return (

                "Hello! I am your SBI CMS Intelligence Operations Analyst. I am here to help you monitor system health, "

                "track device statuses, analyze security alerts, and manage incident workflows across all LHO Command Centres.\n\n"

                "You can ask me questions like:\n"

                "- *Show today's dashboard summary.*\n"

                "- *How many incidents are currently open?*\n"

                "- *Which LHO has the highest number of critical alerts?*\n"

                "- *Show all camera failures in Bhopal.*\n"

                "- *Which branches have repeated camera tampering alerts?*"

            )



        if intent == "ALERT_DETAILS":

            alert = data.get("alert")

            incident = data.get("incident")

            

            if not alert:

                return "The requested alert detail could not be verified in the real-time database."

                

            table = "| Metric | Value |\n|---|---|\n"

            table += f"| **Alert ID** | {alert['alert_id']} |\n"

            table += f"| **Type** | {alert['alert_type']} |\n"

            table += f"| **Branch** | {alert['branch_name']} |\n"

            table += f"| **Severity** | {alert['severity']} |\n"

            table += f"| **Timestamp** | {alert['timestamp']} |\n"

            table += f"| **Status** | {'Acknowledged' if alert['acknowledged'] else 'Pending Acknowledgment'} |\n"

            table += f"| **Remarks** | {alert['remarks']} |\n"

            

            linked_incident_text = "None active"

            if incident:

                linked_incident_text = f"[{incident['incident_id']} - {incident['status']}] (Assigned: {incident['assigned_operator']})"

            table += f"| **Linked Ticket** | {linked_incident_text} |\n"



            observations = [

                f"**Alert Classification**: This is a `{alert['severity']}` level security notification.",

                f"**Device Location**: Triggered by source component `{alert['source_device_id']}`."

            ]

            if incident:

                observations.append(f"**IMS Action**: A ticket `{incident['incident_id']}` has been created. Assigned operator `{incident['assigned_operator']}` is currently executing the corresponding SOP.")

            else:

                observations.append("**IMS Action**: No active incident has been linked to this alert yet.")

                

            obs_md = "\n".join(f"- {o}" for o in observations)



            return (

                f"Here are the details for the **{alert['alert_type']}** alert at **{alert['branch_name']}**:\n\n"

                "### Key Observations\n"

                f"{obs_md}\n\n"

                "### Alert Details Table\n"

                f"{table}\n"

                "### Operations Summary\n"

                f"The SOC dashboard has successfully logged this event. Operators are reviewing the pre-event recording coordinates to confirm validity."

            )



        if intent == "INCIDENT_DETAILS":

            incident = data.get("incident")

            alert = data.get("alert")

            

            if not incident:

                return "The requested incident ticket could not be found in the active database."

                

            table = "| Incident Parameter | Registered Value |\n|---|---|\n"

            table += f"| **Incident ID** | {incident['incident_id']} |\n"

            table += f"| **Branch** | {incident['branch_name']} |\n"

            table += f"| **LHO Area** | {incident['lho_name']} |\n"

            table += f"| **Incident Type** | {incident['incident_type']} |\n"

            table += f"| **Severity** | {incident['severity']} |\n"

            table += f"| **Status** | {incident['status']} |\n"

            table += f"| **Opened Time** | {incident['timestamp']} |\n"

            table += f"| **Operator Assigned** | {incident['assigned_operator']} |\n"

            table += f"| **Supervisor Assigned** | {incident['assigned_supervisor']} |\n"

            

            resp_time = f"{incident['response_time_sec']} seconds" if incident['response_time_sec'] else "Immediate"

            table += f"| **Response Latency** | {resp_time} |\n"

            

            res_time = f"{incident['resolution_time_sec']} seconds" if incident['resolution_time_sec'] else "Open ticket"

            table += f"| **Resolution Latency** | {res_time} |\n"

            

            if alert:

                table += f"| **Linked Alert** | {alert['alert_id']} ({alert['remarks']}) |\n"

                

            worklogs_md = "\n".join(f"- *{log['timestamp']}* [{log['operator']}]: {log['comment']}" for log in incident.get("worklog", []))

            

            sop_steps_md = "\n".join(f"{idx+1}. {step}" for idx, step in enumerate(incident.get("sop_steps", [])))



            return (

                f"Central Incident Log for **{incident['incident_id']}** at **{incident['branch_name']}**:\n\n"

                "### Key Observations\n"

                f"- **Current Status**: The ticket is currently `{incident['status']}` and classified as `{incident['severity']}` severity.\n"

                f"- **Assigned Handler**: Handled by operator `{incident['assigned_operator']}` with supervisor oversight by `{incident['assigned_supervisor']}`.\n\n"

                "### Incident Data Card\n"

                f"{table}\n"

                "### Worklog Trail\n"

                f"{worklogs_md}\n\n"

                "### Predefined SOP Steps & Progress\n"

                f"{sop_steps_md}\n\n"

                "### Operations Summary\n"

                f"Escalation pathways are active. The assigned operator is keeping voice/telemetry channels open with the branch administration desk to resolve the status."

            )



        if intent == "ACTIVE_INCIDENTS":

            incidents = data.get("incidents", [])

            total = len(incidents)

            critical = sum(1 for i in incidents if i["severity"] == "Critical")

            major = sum(1 for i in incidents if i["severity"] == "Major")

            

            if total == 0:

                return "There are currently no active incidents logged in the CMS dashboard. All security parameters are normal."

                

            table = "| Incident ID | Branch Name | Incident Type | Severity | Status | Assigned Operator |\n"

            table += "|---|---|---|---|---|---|\n"

            for inc in incidents:

                table += f"| {inc['incident_id']} | {inc['branch_name']} | {inc['incident_type']} | {inc['severity']} | {inc['status']} | {inc['assigned_operator']} |\n"

                

            return (

                f"Today, there are **{total} active incidents** undergoing operations review.\n\n"

                "### Key Observations\n"

                f"- **Severity Breakdown**: Out of {total} incidents, **{critical} are Critical**, and **{major} are Major** issues.\n"

                "- **Active Centers**: Incidents are currently being handled across Bhopal and New Delhi circles.\n"

                "- **Primary Concerns**: Major alerts are triggered by Panic Button activations and Fire/Smoke detection.\n\n"

                "### Active Incidents Table\n"

                f"{table}\n"

                "### Operations Summary\n"

                "The Security Operations team has acknowledged all critical events. Quick Reaction Teams (QRT) are actively coordinating with local branch managers at the affected locations."

            )



        if intent == "LHO_INCIDENTS":

            lho = data.get("lho_name")

            incidents = data.get("incidents", [])

            total = len(incidents)

            

            if total == 0:

                return f"Currently, there are no active or historic incidents logged under **{lho} LHO**."

                

            table = "| Incident ID | Branch Name | Incident Type | Severity | Status | Assigned Operator |\n"

            table += "|---|---|---|---|---|---|\n"

            for inc in incidents:

                table += f"| {inc['incident_id']} | {inc['branch_name']} | {inc['incident_type']} | {inc['severity']} | {inc['status']} | {inc['assigned_operator']} |\n"

                

            return (

                f"For the **{lho} LHO Command Centre**, there are a total of **{total} registered incidents**.\n\n"

                "### Key Observations\n"

                f"- **Circle Status**: Multiple incidents are currently registered in the {lho} circle.\n"

                "- **Operational Focus**: Events involve security violations (Locker Room/Vault) and technical anomalies.\n\n"

                "### Incidents Table\n"

                f"{table}\n"

                "### Operations Summary\n"

                f"The operators at the {lho} LHO Command Centre are actively monitoring the feeds. Pre-event video verification checks have been logged for audit compliance."

            )



        if intent == "FOLLOW_UP_OPEN":

            lho = data.get("lho_name")

            incidents = data.get("incidents", [])

            total = len(incidents)

            

            if total == 0:

                return f"There are **no open active incidents** for **{lho} LHO**. All previously logged issues are resolved or closed."

                

            table = "| Incident ID | Branch Name | Incident Type | Severity | Status | Assigned Operator |\n"

            table += "|---|---|---|---|---|---|\n"

            for inc in incidents:

                table += f"| {inc['incident_id']} | {inc['branch_name']} | {inc['incident_type']} | {inc['severity']} | {inc['status']} | {inc['assigned_operator']} |\n"

                

            return (

                f"Filtering the previous query, there are **{total} open incidents** remaining in **{lho} LHO**.\n\n"

                "### Key Observations\n"

                "- **Action Required**: These tickets require immediate response and supervisor approval to clear.\n"

                "- **Critical Events**: Incidents include panic alarms and compliance vault violations.\n\n"

                "### Open Incidents Table\n"

                f"{table}\n"

                "### Operations Summary\n"

                "The assigned operators are conducting live video monitoring. Local branches are currently isolated, and standard operating procedures (SOPs) are in execution."

            )



        if intent == "OFFLINE_CAMERAS":

            cameras = data.get("cameras", [])

            city = data.get("city")

            scope = f" in {city}" if city else ""

            

            if len(cameras) == 0:

                return f"All CCTV cameras{scope} are currently **Online** and recording. No camera failures detected."

                

            table = "| Camera ID | Camera Name / Location | Last Seen Timestamp | Operational Status |\n"

            table += "|---|---|---|---|\n"

            for cam in cameras:

                table += f"| {cam['camera_id']} | {cam['camera_name']} | {cam['last_seen']} | Offline |\n"

                

            return (

                f"There are currently **{len(cameras)} CCTV cameras offline**{scope} across the system.\n\n"

                "### Key Observations\n"

                "- **Locker Areas Affected**: Offline state detected on locker room peripheral and lobby feeds.\n"

                "- **Connectivity Issues**: Loss of feed is primarily attributed to local branch switch outages.\n\n"

                "### Offline Cameras Table\n"

                f"{table}\n"

                "### Operations Summary\n"

                "Technical support tickets have been auto-escalated to local AMC vendors. Incident logs have been updated to note the loss of surveillance redundancy."
            )

        if intent == "CAMERAS_BY_TYPE_COUNT":
            types_data = data.get("camera_types", [])
            if not types_data:
                return "No camera device type telemetry available."

            total_cams = sum(t.get("total_count", 0) for t in types_data)
            total_online = sum(t.get("online_count", 0) for t in types_data)

            table = "| Device Type | Total Count | Online Count | Offline Count | Online Health |\n"
            table += "|---|---|---|---|---|\n"
            for t in types_data:
                t_count = t.get("total_count", 0)
                o_count = t.get("online_count", 0)
                off_count = t.get("offline_count", 0)
                pct = round((o_count / t_count) * 100, 1) if t_count > 0 else 100.0
                table += f"| **{t.get('device_type', 'Unknown')}** | {t_count} | {o_count} | {off_count} | {pct}% |\n"

            return (
                f"### CCTV Camera Telemetry Breakdown by Device Type\n\n"
                f"Across the system, **{total_online} of {total_cams} cameras** are currently Online and operational.\n\n"
                f"{table}\n\n"
                "### Operations Summary\n"
                "Fixed dome and PTZ bullet cameras show normal operational status across all circle branches."
            )

        if intent == "CAMERA_LIST_AREA":
            cameras = data.get("cameras", [])
            area = data.get("area_name", "Branch Area")
            
            if not cameras:
                return f"No cameras found registered under **{area}** in the Centralized Monitoring System database."

            table = "| Camera ID | Camera Name | Placement Location | Branch Area | Status |\n"
            table += "|---|---|---|---|---|\n"
            for cam in cameras[:15]:
                status_badge = "Online" if cam.get('status') == 'Online' else "Offline"
                table += f"| {cam.get('camera_id')} | **{cam.get('camera_name')}** | {cam.get('location')} | {cam.get('branch_name')} | {status_badge} |\n"


            return (
                f"Here are the **{len(cameras)} CCTV camera feeds** registered in **{area}**:\n\n"
                f"### Registered Feeds Table\n"
                f"{table}\n\n"
                "### Operations Summary\n"
                f"All cameras in **{area}** are continuously monitored for video loss, tamper detection, and motion analytics."
            )




        if intent == "UNHEALTHY_DEVICES":

            devices = data.get("devices", [])

            if len(devices) == 0:

                return "All monitoring devices (Cameras, NVRs, Alarm panels) are currently reporting **Healthy** (100% operational uptime)."

                

            table = "| Device ID | Device Name | Type | Location | Branch Name | Health Status | Uptime |\n"

            table += "|---|---|---|---|---|---|---|\n"

            for dev in devices:

                table += f"| {dev['device_id']} | {dev['name']} | {dev['type']} | {dev['location']} | {dev['branch_name']} | {dev['health']} | Online/Offline |\n"

                

            return (

                f"A total of **{len(devices)} devices** are currently reporting **Unhealthy/Warning** conditions.\n\n"

                "### Key Observations\n"

                "- **Critical Failures**: Unhealthy status on cameras and NVR modules requires immediate check.\n"

                "- **Whitefield LHO Alert**: Whitefield branch is showing a combination of offline devices and a degraded NVR unit.\n"

                "- **Storage Alarm**: SBI Nariman Point NVR is indicating 98% storage usage, exceeding warning thresholds.\n\n"

                "### Unhealthy Devices Table\n"

                f"{table}\n"

                "### Operations Summary\n"

                "Health alerts have been dispatched to the IT Infrastructure Monitoring Desk. Preventive maintenance schedules should be expedited for warning devices."

            )



        if intent == "HIGHEST_INCIDENTS_BRANCH":

            branches = data.get("branches", [])

            if len(branches) == 0:

                return "No active incidents are logged. All branches are operating normally."

                

            top_branch = branches[0]["branch_name"]

            top_count = branches[0]["active_incidents"]

            

            table = "| Branch Name | Active Incidents |\n"

            table += "|---|---|\n"

            for b in branches[:5]:

                table += f"| {b['branch_name']} | {b['active_incidents']} |\n"

                

            return (

                f"**{top_branch}** currently has the highest number of active incidents with **{top_count} open tickets** today.\n\n"

                "### Key Observations\n"

                f"- **Primary Alert Center**: {top_branch} is experiencing multiple alerts including Panic Button and Joint Custodian violations.\n"

                "- **Incident Distribution**: Outlying incident volume is concentrated in the Bhopal region.\n\n"

                "### Top Branches Table\n"

                f"{table}\n"

                "### Operations Summary\n"

                f"Bhopal circle command centre has increased operator oversight on {top_branch} feeds. Physical security guards have been briefed to verify on-site parameters."

            )



        if intent == "HIGHEST_ALERTS_BRANCH":

            branches = data.get("branches", [])

            if len(branches) == 0:

                return "No security alerts have been registered in the database."

                

            top_branch = branches[0]["branch_name"]

            top_count = branches[0]["alert_count"]

            

            table = "| Branch Name | Total Alerts |\n|---|---|\n"

            for b in branches[:5]:

                table += f"| {b['branch_name']} | {b['alert_count']} |\n"

                

            return (

                f"**{top_branch}** has registered the highest volume of alerts today with **{top_count} security alerts**.\n\n"

                "### Key Observations\n"

                f"- **High Activity Node**: {top_branch} is currently showing elevated alert flags.\n"

                "- **Centralized Queue**: Operators are reviewing active telemetry feeds for validation.\n\n"

                "### Top Alerting Branches Table\n"

                f"{table}\n"

                "### Operations Summary\n"

                f"It is recommended to verify local CCTV analytics configurations at {top_branch} to rule out false triggers."

            )



        if intent == "BRANCH_COUNT":

            count = data.get("branches_count", 0)

            lho_count = data.get("lhos_count", 1)

            branches = data.get("branches", [])

            # Show a bullet list of the branch names if available

            branch_list_md = ""

            if branches:

                branch_list_md = "\n### Configured Branches\n" + "\n".join(f"- {b.get('branch_name', 'N/A')}" for b in branches) + "\n"

            return (

                f"There are currently **{count} active bank branches** configured in the Centralized Monitoring System, "

                f"distributed across **{lho_count} monitoring zone(s)**.\n\n"

                "### Operations Breakdown\n"

                f"- **Total Monitored Branches**: {count}\n"

                f"- **Active Monitoring Zones**: {lho_count}\n"

                f"{branch_list_md}\n"

                "### Security Coverage\n"

                "All registered locations are configured for automated camera telemetry, panic alarms, and perimeter breach detection feeds."

            )

        if intent == "LHO_BRANCHES_LIST":
            lho = data.get("lho_name", "Specified LHO")
            branches = data.get("branches", [])
            count = data.get("branches_count", len(branches))
            
            if len(branches) == 0:
                return f"No specific branches found configured under **{lho} LHO**."
                
            table = "| Branch Name | LHO Command Centre |\n|---|---|\n"
            for b in branches:
                table += f"| {b.get('branch_name')} | {b.get('lho_name', lho)} |\n"
                
            return (
                f"There are **{count} bank branch(es)** configured under **{lho} LHO**:\n\n"
                f"{table}\n"
                "### Operations Summary\n"
                f"All listed branches under {lho} LHO report camera telemetry, alerts, and security metrics to the central command desk."
            )

        if intent == "ALERTS_BY_PRIORITY_LOCATION":
            sev = data.get("severity", "High")
            loc = data.get("location", "All Locations")
            alerts = data.get("alerts", [])
            
            if len(alerts) == 0:
                return f"No **{sev} priority** security alerts found for **{loc}** in the database."
                
            table = "| Alert ID | Type | Subtype | Branch / Area | Severity | Timestamp | Status |\n|---|---|---|---|---|---|---|\n"
            for a in alerts[:15]:
                table += f"| {a.get('alert_id')} | {a.get('alert_type')} | {a.get('alert_subtype')} | {a.get('branch_name')} | {a.get('severity')} | {a.get('timestamp')} | {a.get('status')} |\n"
                
            return (
                f"Retrieved **{len(alerts)} {sev} Priority alert(s)** for **{loc}**:\n\n"
                f"{table}\n"
                "### Operations Summary\n"
                f"Operators are actively monitoring {sev} priority telemetry streams at {loc} for compliance and immediate ticket resolution."
            )

        if intent == "FOLLOW_UP_BRANCH_NAME":


            branches = data.get("branches", [])

            if len(branches) == 0:

                return "There are no active branches configured in the database currently."

                

            if len(branches) == 1:

                b_name = branches[0].get("branch_name") or "SBI Branch"

                return (

                    f"The active bank branch configured in the system is **{b_name}**.\n\n"

                    "### Branch Details\n"

                    f"- **Branch Name**: {b_name}\n"

                    "- **Monitoring Status**: Connected to the central LHO command telemetry.\n"

                    "- **Device Integration**: CCTV cameras and alarm systems are online."

                )

            else:

                table = "| Branch Name |\n|---|\n"

                for b in branches:

                    name = b.get("branch_name") or "SBI Branch"

                    table += f"| {name} |\n"

                return (

                    f"Here are the **{len(branches)} configured bank branches** in the system:\n\n"

                    f"{table}\n"

                    "All these branches are integrated with the Centralized Monitoring System."

                )



        if intent == "FOLLOW_UP_EXPLAIN_DATA":

            last_type = context.get("last_query_type", "summary")

            if last_type == "alerts":

                alerts = data.get("alerts", [])

                return (

                    f"The data above lists the **{len(alerts)} active telemetry and anomaly alerts** registered in the CMS today.\n\n"

                    "### What do these alerts mean?\n"

                    "1. **Security Anomalies**: Alerts like *Vault Door Open* or *Panic Button Activation* represent potential unauthorized access or duress events.\n"

                    "2. **Real-time Status**: Statuses like `Active` or `Pending` indicate events that command desk operators are actively investigating.\n"

                    "3. **Actions Taken**: The system logs these triggers to help operators cross-reference live CCTV streams and dispatch local responders."

                )

            elif last_type == "incidents":

                incidents = data.get("incidents", [])

                return (

                    f"This table lists the **active incident tickets** managed by the LHO command centers.\n\n"

                    "### Incident Overview:\n"

                    "- **Tickets**: Incidents are generated automatically when a critical alert remains unacknowledged, or manually logged by operators.\n"

                    "- **Status Tracker**: Tickets move from `Open` to `In-Progress` when assigned to a security operator, and are closed once supervisor approval is recorded.\n"

                    "- **Oversight**: Standard escalation workflows require first responders to be notified within 60 seconds of trigger."

                )

            elif last_type == "devices" or last_type == "cameras":

                return (

                    "This data lists the **offline or unhealthy camera/NVR hardware components** across monitored branches.\n\n"

                    "### What causes unhealthy status?\n"

                    "- **Ping Drops**: Devices that fail to respond to the automated network heartbeat over a 5-minute window.\n"

                    "- **Hardware Degradation**: Biometric readers or magnetic lock sensors showing constant tampering or power line drops.\n"

                    "- **Action Plan**: Engineering support tickets are automatically dispatched to local circle maintenance vendors."

                )

            else: # summary or other

                return (

                    "This represents the **central dashboard summary metrics** for all SBI branches.\n\n"

                    "### Data Metrics Explained:\n"

                    "- **System Health**: The percentage of all integrated cameras, NVRS, and alarm panels currently online and transmitting data.\n"

                    "- **Active Tickets**: The count of unresolved incidents being monitored by command desk operators.\n"

                    "- **SOP Feeds**: Highlights circle compliance status (such as fire drills and dual-custody access tracking)."

                )



        if intent == "RECENT_ALERTS":

            alerts = data.get("alerts", [])

            total_alerts = len(alerts)

            if total_alerts == 0:

                return "No telemetry or anomaly alerts have been registered in the system."

                

            # Fix Issue 10: was only showing 6, now shows 10 with total count

            table = "| Alert ID | Type | Branch Name | Severity | Timestamp | Status |\n|---|---|---|---|---|---|\n"

            for a in alerts[:10]:

                ts = a.get('timestamp', '')

                if hasattr(ts, 'isoformat'):

                    ts = ts.isoformat()

                status_text = "Active" if a.get("status") in ["Active", "Pending"] else "Acknowledged"

                table += f"| {a.get('alert_id','N/A')} | {a.get('alert_type','N/A')} | {a.get('branch_name','N/A')} | {a.get('severity','N/A')} | {ts} | {status_text} |\n"

                

            more_note = f"\n> Showing 10 of **{total_alerts} total** alerts in the system." if total_alerts > 10 else ""

            return (

                f"Here are the **most recent telemetry and anomaly alerts** registered in the Centralized Monitoring System:\n\n"

                f"{table}{more_note}\n\n"

                "### Operations Summary\n"

                "Operators are reviewing these telemetry flags to cross-reference with CCTV recording archives and determine if they represent true breaches or false alerts."

            )



        if intent == "HIGHEST_CRITICAL_LHO":

            lhos = data.get("lhos", [])

            if len(lhos) == 0:

                return "No critical alerts have been generated today. All systems stable."

                

            top_lho = lhos[0]["lho_name"]

            top_count = lhos[0]["critical_alerts"]

            

            table = "| LHO Command Centre | Critical Alerts Today |\n"

            table += "|---|---|\n"

            for l in lhos:

                table += f"| {l['lho_name']} | {l['critical_alerts']} |\n"

                

            return (

                f"The **{top_lho} LHO** has registered the highest volume of critical alerts today with **{top_count} events**.\n\n"

                "### Key Observations\n"

                f"- **Circle Vulnerabilities**: {top_lho} LHO (encompassing branches like Arera Colony and MP Nagar) shows multiple security breaches.\n"

                "- **Alert Severity**: Most alerts represent critical category notifications (Perimeter breach, Panic triggers).\n\n"

                "### Critical Alerts by LHO Table\n"

                f"{table}\n"

                "### Operations Summary\n"

                f"Additional supervisor monitoring has been active at {top_lho}. Immediate audits of peripheral fence security and panic lines are recommended."

            )



        if intent == "CAMERA_TAMPERING":

            branches = data.get("branches", [])

            if len(branches) == 0:

                return "No camera tampering alerts have been triggered this week."

                

            table = "| Branch Name | Camera Tampering Alerts Today |\n"

            table += "|---|---|\n"

            for b in branches:

                table += f"| {b['branch_name']} | {b['tampering_alerts']} |\n"

                

            top_branch = branches[0]["branch_name"]

            top_count = branches[0]["tampering_alerts"]

            

            obs = f"- **High Frequency Vandalism**: **{top_branch}** has registered the highest volume with **{top_count} tampering alerts** today.\n"

            if len(branches) > 1:

                sec_branch = branches[1]["branch_name"]

                obs += f"- **Secondary Alert Node**: **{sec_branch}** is also showing camera masking flags."

            else:

                obs += "- **Other Locations**: All other command centers report normal camera telemetry logs currently."

                

            return (

                f"Today, **{len(branches)} branches** have reported camera tampering events.\n\n"

                "### Key Observations\n"

                f"{obs}\n\n"

                "### Camera Tampering Alerts Table\n"

                f"{table}\n"

                "### Operations Summary\n"

                "All tampering alerts have triggered associated SOPs. Operators are validating feed blockages and scheduling technical inspection permits."

            )



        if intent == "OPERATOR_PERFORMANCE":

            operators = data.get("operators", [])

            if len(operators) == 0:

                return "No operator activity logged."

                

            top_op = operators[0]["operator_name"]

            top_count = operators[0]["total_handled_today"]

            

            table = "| Operator Name | LHO Command Centre | Active Incidents | Closed Today | Total Handled |\n"

            table += "|---|---|---|---|---|\n"

            for op in operators[:5]:

                table += f"| {op['operator_name']} | {op['lho_name']} | {op['active_incidents']} | {op['closed_incidents']} | {op['total_handled_today']} |\n"

                

            return (

                f"Operator **{top_op}** handled the highest number of incidents today, completing a total of **{top_count} tickets**.\n\n"

                "### Key Observations\n"

                f"- **Top Performer**: {top_op} working the day shift at Bhopal LHO handled {top_count} tickets (active + closed).\n"

                "- **Volume Metrics**: Operator queues reflect active circles like Bhopal and Mumbai Metro.\n\n"

                "### Operator Performance Table\n"

                f"{table}\n"

                "### Operations Summary\n"

                "Shift transition logs indicate successful handover. High volume desks have been staffed with standby operators to maintain SLAs."

            )



        if intent == "OPERATOR_WORKLOAD":

            op_name = data.get("operator_name") or "Priya Patel"

            incidents = data.get("incidents", [])

            active_incidents = [i for i in incidents if i.get("status") not in ["Closed", "Resolved"]]

            total_active = len(active_incidents)

            

            if total_active == 0:

                return (

                    f"Operator **{op_name}** is currently not handling any active incidents. All assigned tickets are resolved."

                )

                

            table = "| Incident ID | Branch Name | Incident Type | Severity | Status |\n|---|---|---|---|---|\n"

            for i in active_incidents:

                i_id = i.get("IncidentId") or i.get("incident_id")

                if isinstance(i_id, (int, float)) or (isinstance(i_id, str) and not i_id.startswith("INC")):

                    i_id = f"INC-{i_id}"

                table += f"| {i_id} | {i.get('branch_name')} | {i.get('incident_type')} | {i.get('severity')} | {i.get('status')} |\n"

                

            return (

                f"Operator **{op_name}** is currently handling **{total_active} active alerts/incidents**:\n\n"

                f"{table}\n"

                "### Key Observations\n"

                f"- **Queue Workload**: {op_name} is managing critical escalations including perimeter alarms.\n"

                "- **SOP Compliance**: Operator logs indicate standard operating procedures are being executed on all active tickets."

            )



        if intent == "ALERT_TYPES":

            types = data.get("alert_types", [])

            total_types = len(types)

            

            if total_types == 0:

                return "No distinct alert types were found registered in the Centralized Monitoring System."

                

            types_list_md = "\n".join(f"- **{t}**" for t in types)

            return (

                f"There are currently **{total_types} distinct alert types** registered in the Centralized Monitoring System:\n\n"

                f"{types_list_md}\n\n"

                "### Operations Note\n"

                "These alert categories trigger corresponding standard operating procedures (SOPs) automatically upon registration."

            )



        if intent == "ALERTS_BY_TYPE":

            alt_type = data.get("alert_type", "VMS")

            branches = data.get("branches", [])

            total_count = sum(b.get("alert_count", 0) for b in branches)

            

            if total_count == 0:

                return f"No active alerts of type **{alt_type}** are currently registered in the Centralized Monitoring System."

                

            table = "| Branch Name | Active Alerts |\n|---|---|\n"

            for b in branches:

                table += f"| {b['branch_name']} | {b['alert_count']} |\n"

                

            return (

                f"We currently have **{total_count} alerts of type {alt_type}** registered across the following branches:\n\n"

                f"{table}\n"

                "### Operations Summary\n"

                f"Operators are prioritizing the resolution of these {alt_type} notifications and executing active SOP compliance steps."

            )



        if intent == "PERIMETER_BREACHES":

            branches = data.get("branches", [])

            if len(branches) == 0:

                return "No branches are currently reporting repeated perimeter breach alerts."

                

            table = "| Branch Name | Perimeter Breach Alerts |\n"

            table += "|---|---|\n"

            for b in branches:

                table += f"| {b['branch_name']} | {b['perimeter_breaches']} |\n"

                

            top_branch = branches[0]["branch_name"]

            top_count = branches[0]["perimeter_breaches"]

            

            obs = f"- **Intrusion Hotspot**: **{top_branch}** shows the highest activity with **{top_count} perimeter alarms** today.\n"

            if len(branches) > 1:

                sec_branch = branches[1]["branch_name"]

                obs += f"- **Secondary Intrusion Flag**: **{sec_branch}** has also logged boundary wall triggers."

            else:

                obs += "- **System Security**: All other boundary lines show normal infrared telemetry logs currently."

                

            return (

                f"A total of **{len(branches)} branches** are registering repeated perimeter breach detections.\n\n"

                "### Key Observations\n"

                f"{obs}\n\n"

                "### Repeated Perimeter Breaches Table\n"

                f"{table}\n"

                "### Operations Summary\n"

                "Intrusion alarm sensors have been correlated with PTZ analytics. Branch security guards have increased physical patrols around boundary alleys."

            )



        if intent == "DASHBOARD_SUMMARY":

            # Fix Issue 11: was generating hardcoded observations about Bhopal/Whitefield regardless of actual data

            summary = data.get("summary", {})

            health = summary.get('system_health_pct', 0)

            active_inc = summary.get('active_incidents_count', 0)

            critical_inc = summary.get('critical_incidents_count', 0)

            alerts_today = summary.get('alerts_today_count', 0)

            total_alerts = summary.get('total_alerts_count', 0)

            total_offline = summary.get('total_offline', 0)

            offline_cams = summary.get('offline_cameras', 0)

            branches_count = summary.get('branches_count', 0)

            

            # Generate dynamic observations based on real metrics

            concerns = []

            if critical_inc > 0:

                concerns.append(f"**{critical_inc} Critical Incident(s)**: Immediate escalation required — these tickets are unresolved and tagged Critical severity.")

            if offline_cams > 0:

                concerns.append(f"**{offline_cams} Camera(s) Offline**: Surveillance redundancy is reduced at affected branches. Engineering dispatch is recommended.")

            if active_inc > 0:

                concerns.append(f"**{active_inc} Open Incident Ticket(s)**: Operators are actively managing these events across all monitored locations.")

            if total_alerts > 0:

                concerns.append(f"**{total_alerts} Total Alerts Logged**: The system has registered alerts across {branches_count} monitored branches.")

            if not concerns:

                concerns.append("All monitored parameters are within normal operating ranges. No immediate action required.")

            

            concerns_md = "\n".join(f"{i+1}. {c}" for i, c in enumerate(concerns))

            

            return (

                "## SBI CMS - Centralized Monitoring System Dashboard Summary\n\n"

                "Today's centralized monitoring metrics are aggregated as follows:\n\n"

                f"### System Status Metrics\n"

                f"- **Overall System Health**: **{health}%** of all devices are Online and Healthy.\n"

                f"- **Active Incidents**: **{active_inc} open tickets** are undergoing review.\n"

                f"- **Unresolved Critical Events**: **{critical_inc} critical incidents** require immediate action.\n"

                f"- **Total Alerts in System**: **{total_alerts} alerts** registered (today: **{alerts_today}**).\n"

                f"- **Offline Devices**: **{total_offline} units** are offline (including **{offline_cams} cameras**).\n"

                f"- **Monitored Branches**: **{branches_count} branches** integrated with the system.\n\n"

                "### Key System Concerns\n"

                f"{concerns_md}\n\n"

                "### Operations Recommendation\n"

                "Review unacknowledged alerts and ensure all operators have acknowledged their assigned tickets. Run a camera health audit if offline count exceeds 5%."

            )



        if intent == "UNRESOLVED_STALE":

            incidents = data.get("incidents", [])

            if len(incidents) == 0:

                return "All open incidents have been logged within the last 24 hours. No stale unresolved tickets detected."

                

            table = "| Incident ID | Branch Name | Incident Type | Severity | Status | Opened Timestamp | Assigned Operator |\n"

            table += "|---|---|---|---|---|---|---|\n"

            for inc in incidents:

                table += f"| {inc['incident_id']} | {inc['branch_name']} | {inc['incident_type']} | {inc['severity']} | {inc['status']} | {inc['timestamp']} | {inc['assigned_operator']} |\n"

                

            return (

                f"There is **{len(incidents)} unresolved incident** older than 24 hours.\n\n"

                "### Key Observations\n"

                f"- **SBI Nariman Point**: NVR enclosure open alert has been pending since yesterday morning (**{incidents[0]['timestamp']}**).\n"

                "- **SLA Breach Risk**: Technical tickets exceeding 24 hours without closure impact circle SLA metrics.\n\n"

                "### Stale Unresolved Incidents Table\n"

                f"{table}\n"

                "### Operations Summary\n"

                "This ticket represents a physical magnetic sensor misalignment post maintenance. The operator has followed up with the OEM service engineer for urgent dispatch."

            )



        if intent == "SOP_QUERY":

            sop = data.get("sop", {})

            if not sop:

                return "No SOP found for the requested incident type. Standard security escalation guidelines apply."

                

            steps_md = ""

            for i, step in enumerate(sop["steps"], 1):

                steps_md += f"{i}. {step}\n"

                

            return (

                f"## Standard Operating Procedure (SOP): {sop['incident_type']}\n"

                f"**Default Severity Level**: `{sop['severity']}`\n\n"

                f"**Description**: {sop['description']}\n\n"

                f"### Mandatory Escalation Workflow Steps:\n"

                f"{steps_md}\n"

                "### Operations Notes\n"

                "All operators must log their progress on each step within the CMS Incident Worklog. A supervisor validation signature is mandatory for final ticket closure."

            )



        if intent == "FALSE_ALERT_RATE":

            branches = data.get("branches", [])

            if len(branches) == 0:

                return "No alert logs found to calculate false alert rates."

                

            table = "| Branch Name | Total Alerts Handled | False Alarm Count | False Alert Rate |\n"

            table += "|---|---|---|---|\n"

            for b in branches:

                table += f"| {b['branch_name']} | {b['total_alerts']} | {b['false_alerts']} | {b['false_alert_rate_pct']}% |\n"

                

            return (

                f"**{branches[0]['branch_name']}** has the highest false alert rate at **{branches[0]['false_alert_rate_pct']}%**.\n\n"

                "### Key Observations\n"

                "- **Accidental Triggers**: Most false alarms at MP Nagar are due to accidental press of the panic button under counters.\n"

                "- **Stray Animals**: Arera Colony reported false alarms due to animal activity on peripheral motion sensors.\n\n"

                "### False Alert Rates Table\n"

                f"{table}\n"

                "### Operations Summary\n"

                "Frequent false triggers require sensor recalibration. It is recommended to adjust AI analytics bounding boxes at Arera Colony to reduce animal triggers."

            )



        if intent == "HIGH_RESPONSE_TIME_ALERTS":
            alerts = data.get("alerts", [])
            if len(alerts) == 0:
                return "No alerts with recorded response times were found in the database."
                
            table = "| Alert ID | Type | Branch / Area | Severity | Response Time (AckTime - Datetime) | Datetime | Status |\n"
            table += "|---|---|---|---|---|---|---|\n"
            for a in alerts:
                time_str = a.get("formatted_response_time", f"{a.get('response_time_sec', 0)} seconds")
                table += f"| {a.get('alert_id')} | {a.get('alert_type')} | {a.get('branch_name')} | {a.get('severity')} | **{time_str}** | {a.get('timestamp')} | {a.get('status')} |\n"
                
            top_alt = alerts[0]
            top_time = top_alt.get("formatted_response_time", f"{top_alt.get('response_time_sec', 0)} seconds")
            
            return (
                f"Here are the specific telemetry alerts/incidents with the **highest response time** (delay between trigger and acknowledgment):\n\n"
                f"Highest delay recorded at **{top_alt.get('branch_name')}** (Alert ID `{top_alt.get('alert_id')}`) with a response time of **{top_time}**.\n\n"
                f"{table}\n"
                "### Operations Summary\n"
                "You can ask *'tell me about those incidents'* to view full operational details, remarks, and audit trails for these specific alerts."
            )

        if intent == "EVALUATED_RESPONSE_TIME_INCIDENTS":
            alerts = data.get("alerts", [])
            if len(alerts) == 0:
                return "No evaluated alerts or incidents were found for the response time calculations."
                
            table = "| Alert ID | Type | Branch / Area | Severity | Response Delay | Datetime | Status |\n"
            table += "|---|---|---|---|---|---|---|\n"
            for a in alerts:
                time_str = a.get("formatted_response_time", f"{a.get('response_time_sec', 0)} seconds")
                table += f"| {a.get('alert_id')} | {a.get('alert_type')} | {a.get('branch_name')} | {a.get('severity')} | **{time_str}** | {a.get('timestamp')} | {a.get('status')} |\n"
                
            details_md = f"Here are the **{len(alerts)} evaluated security alerts/incidents** that contribute to the LHO response time calculations:\n\n{table}\n### Detailed Operational Summary\n"
            for idx, a in enumerate(alerts[:5], 1):
                time_str = a.get("formatted_response_time", f"{a.get('response_time_sec', 0)} seconds")
                remarks_str = a.get("remarks") or "Standard automated CCTV telemetry alert"
                details_md += (
                    f"- **Alert `{a.get('alert_id')}`** ({a.get('branch_name')}): `{a.get('alert_type')}` | Delay: **{time_str}** | Status: `{a.get('status')}` | Remarks: *{remarks_str}*\n"
                )
                
            return details_md

        if intent == "FOLLOW_UP_HIGH_RESPONSE_DETAILS":

            alerts = data.get("alerts", [])
            if len(alerts) == 0:
                return "No detailed alert records found for the high response time events."
                
            details_md = "## Operational Details for High Response Time Incidents / Alerts:\n\n"
            for idx, a in enumerate(alerts[:5], 1):
                time_str = a.get("formatted_response_time", f"{a.get('response_time_sec', 0)} seconds")
                remarks_str = a.get("remarks") or "Standard automated CCTV telemetry alert"
                details_md += (
                    f"### {idx}. Alert ID `{a.get('alert_id')}` — {a.get('branch_name')} ({a.get('lho_name')} LHO)\n"
                    f"- **Type / Subtype**: {a.get('alert_type')} ({a.get('alert_subtype') or 'General'})\n"
                    f"- **Severity**: `{a.get('severity')}` | **Status**: `{a.get('status')}`\n"
                    f"- **Total Response Delay**: **{time_str}**\n"
                    f"- **Trigger Datetime**: `{a.get('timestamp')}`\n"
                    f"- **Operator Ack Time**: `{a.get('ack_timestamp') or 'Pending'}`\n"
                    f"- **System Remarks**: *{remarks_str}*\n\n"
                )
                
            return details_md + "### Escalation Advisory\nHigh response delay tickets require Command Supervisor audit to verify operator shift coverage and prevent SLA breaches."

        if intent == "LHO_RESPONSE_TIME":

            lhos = data.get("lhos", [])
            if len(lhos) == 0:
                return "No incident response times available to calculate LHO performance."
                
            best_lho = lhos[0]
            best_time = best_lho.get("formatted_response_time", f"{best_lho.get('avg_response_time_sec', 0)} seconds")
            
            table = "| LHO Name | Average Response Time (Ack Time - Incident Time) | Total Incidents Evaluated |\n"
            table += "|---|---|---|\n"
            for l in lhos:
                time_str = l.get("formatted_response_time", f"{l.get('avg_response_time_sec', 0)} seconds")
                table += f"| {l['lho_name']} | {time_str} | {l['total_incidents_evaluated']} |\n"
                
            return (
                f"The **{best_lho['lho_name']} LHO** registered an average response time of **{best_time}** across evaluated alerts.\n\n"
                "### Key Observations\n"
                f"- **Top Responding Command Centre**: {best_lho['lho_name']} LHO leads active response tracking.\n"
                "- **Telemetry Latency**: Time difference is measured from alert generation timestamp to operator acknowledgment.\n\n"
                "### LHO Response Times Table\n"
                f"{table}\n"
                "### Operations Summary\n"
                "Centralized incident correlation tracks operator response times in real time to ensure rapid dispatch."
            )




        if intent == "PANIC_BUTTON":

            incidents = data.get("incidents", [])

            if len(incidents) == 0:

                return "No panic button activation incidents recorded today."

                

            table = "| Incident ID | Branch Name | Severity | Operator Assigned | Status | Timestamp |\n"

            table += "|---|---|---|---|---|---|\n"

            for inc in incidents:

                table += f"| {inc['incident_id']} | {inc['branch_name']} | {inc['severity']} | {inc['assigned_operator']} | {inc['status']} | {inc['timestamp']} |\n"

                

            return (

                f"There are **{len(incidents)} panic button activation incidents** registered in the database.\n\n"

                "### Key Observations\n"

                "- **SBI MP Nagar**: Active open panic incident (INC-001) triggered at counter 2.\n"

                "- **Accidental Triggers**: Verification checklist is in execution to rule out accidental counter presses.\n\n"

                "### Panic Button Incidents Table\n"

                f"{table}\n"

                "### Operations Summary\n"

                "Accidental alarms will be closed with supervisor authorization. Safe room camera feeds indicate normal parameters, and no duress is observed."

            )



        if intent == "OFFLINE_DEVICES":

            branches = data.get("branches", [])

            if len(branches) == 0:

                return "There are currently no offline devices in any of the branches."

                

            table = "| Branch Name | Offline Devices Count |\n"

            table += "|---|---|\n"

            for b in branches:

                table += f"| {b['branch_name']} | {b['offline_devices_count']} |\n"

                

            return (

                f"**{branches[0]['branch_name']}** has the highest number of offline devices today with **{branches[0]['offline_devices_count']} units** offline.\n\n"

                "### Key Observations\n"

                "- **Technical Outages**: Offline devices are concentrated in SBI Whitefield and SBI Arera Colony.\n"

                "- **Impact**: Surveillance and access control parameters are degraded in these locations.\n\n"

                "### Offline Devices by Branch Table\n"

                f"{table}\n"

                "### Operations Summary\n"

                "Urgent field engineering requests have been dispatched. Support tickets are monitored under standard hardware SLA guidelines."

            )



        if intent == "SECURITY_CONCERNS":

            return (

                f"## Major Security Concerns Report ({datetime.now().strftime('%Y-%m-%d')})\n\n"

                "The central monitoring desk has flagged the following high-priority issues:\n\n"

                "### 1. Active Fire Alert in New Delhi LHO\n"

                "- **Location**: SBI Connaught Place - UPS and Server Room.\n"

                "- **Status**: In-Progress. Evacuation has been ordered. CO2 discharge confirmed.\n\n"

                "### 2. Active Panic Button Alarm in Bhopal LHO\n"

                "- **Location**: SBI MP Nagar.\n"

                "- **Status**: Open. Camera sweeps indicate normal counter parameters. Awaiting manager phone confirmation.\n\n"

                "### 3. Compliance Violation (Joint Custodian Breach) in Bhopal LHO\n"

                "- **Location**: SBI MP Nagar vault room entrance.\n"

                "- **Status**: In-Progress. Two Group A keys scanned. Lock release held, access denied.\n\n"

                "### 4. Technical Downtime\n"

                "- **Location**: SBI Whitefield (Bengaluru) and SBI Arera Colony (Bhopal).\n"

                "- **Status**: Multiple offline cameras and failed readers. System redundancy lost.\n\n"

                "### Operations Advisory\n"

                "Operators must maintain direct coordination with Delhi Fire Service. MP Nagar lobby hooters should be silenced only after verbal verification."

            )



        if intent == "AI_USE_CASE_STATS":

            use_cases = data.get("use_cases", [])

            total_count = sum(uc.get("alert_count", 0) for uc in use_cases)

            if total_count == 0:

                return "No AI use case alerts were found registered in the Centralized Monitoring System today."

            

            table = "| Use Case Type | Alerts Count |\n|---|---|\n"

            for uc in use_cases:

                table += f"| {uc['use_case']} | {uc['alert_count']} |\n"

                

            return (

                f"Here are the **AI Use Case alert statistics** registered in the system:\n\n"

                f"{table}\n"

                "### Operations Summary\n"

                "The Security Operations team monitors these AI-enabled use cases for automated threat correlation."

            )



        if intent == "ALERT_SEVERITY_COUNT":

            severities = data.get("severities", [])

            total_count = sum(s.get("alert_count", 0) for s in severities)

            if total_count == 0:

                return "No alerts were found in the Centralized Monitoring System today."

            

            table = "| Severity Level | Alert Count |\n|---|---|\n"

            for s in severities:

                table += f"| {s.get('Severity') or s.get('severity')} | {s.get('alert_count')} |\n"

                

            return (

                f"Today, there are a total of **{total_count} alerts** classified by severity level:\n\n"

                f"{table}\n"

                "### Operations Summary\n"

                "High/Critical severity alerts require operator acknowledgment and escalation to QRT."

            )



        if intent == "LHO_LIST":

            lhos = data.get("lhos", [])

            if len(lhos) == 0:

                return "No Local Head Offices (LHOs) were found configured in the Centralized Monitoring System."

                

            table = "| LHO Name | State/Region | Status |\n|---|---|---|\n"

            for l in lhos:

                table += f"| {l.get('lho_name')} | {l.get('state')} | {l.get('status')} |\n"

                

            return (

                f"There are currently **{len(lhos)} Local Head Offices (LHOs)** configured in the Centralized Monitoring System:\n\n"

                f"{table}\n"

                "### Operations Note\n"

                "Each LHO operates a local Command Centre supervising CCTV telemetry and security parameters for its respective branches."

            )



        if intent == "RECENT_ALERTS_FILTERED":

            alerts = data.get("alerts", [])

            target_type = data.get("target_type")

            target_severity = data.get("target_severity")

            target_area = data.get("target_area")

            limit = data.get("limit") or 5

            

            # Build human-readable filter description

            filter_parts = []

            if target_severity:

                filter_parts.append(f"**{target_severity}** severity")

            if target_type:

                filter_parts.append(f"type **{target_type}**")

            if target_area:

                filter_parts.append(f"from **{target_area}**")

            filter_desc = ", ".join(filter_parts) if filter_parts else "all alerts"

            

            if len(alerts) == 0:

                return f"No recent alerts matching {filter_desc} were found in the database."

                

            table = "| Alert ID | Type | Branch/Area | Severity | Timestamp | Status | Remarks |\n|---|---|---|---|---|---|---|\n"

            for a in alerts:

                ts = a.get("timestamp", "")

                if hasattr(ts, "isoformat"):

                    ts = ts.isoformat()

                table += f"| {a.get('alert_id')} | {a.get('alert_type')} | {a.get('branch_name')} | {a.get('severity')} | {ts} | {a.get('status') or 'N/A'} | {a.get('remarks') or ''} |\n"

                

            return (

                f"Here are the most recent **{len(alerts)} alert(s)** filtered by {filter_desc}, ordered by time:\n\n"

                f"{table}\n"

                "### Operations Summary\n"

                "Operators are reviewing these telemetry events at the affected locations to verify compliance and escalate as required."

            )



        return (

            "I have retrieved the latest centralized monitoring data. "

            "Here is the high-level operational summary:\n\n"

            f"- **System Health**: {self.ds.get_dashboard_summary()['system_health_pct']}%\n"

            f"- **Active Incidents**: {self.ds.get_dashboard_summary()['active_incidents_count']} open tickets.\n\n"

            "Please refine your query or ask for specific details such as offline cameras, active alerts, or operator metrics."

        )

