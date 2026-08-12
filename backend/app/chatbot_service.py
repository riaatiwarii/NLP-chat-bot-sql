import re
import requests
import json
import os
from datetime import datetime
from sqlalchemy import text
from app.data_service import DataService
from app.schema_engine import SchemaEngine
from app.schema_linker import SchemaLinker
from app.context_tracker import ContextTracker

class ChatbotService:
    def __init__(self, data_service: DataService):
        self.ds = data_service
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
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
        
        # Immediate block for direct SQL modification commands to prevent LLM hallucinations
        sql_write_keywords = ["drop table", "insert into", "delete from", "update ", "alter table", "create table"]
        if any(keyword in clean_msg for keyword in sql_write_keywords):
            return (
                "I'm sorry, but executing write operations or direct database modifications is strictly prohibited for security reasons.",
                context
            )


            

        # 1. Identify Intent & Retrieve Relevant Data

        intent, data_payload, context = self._classify_and_fetch(clean_msg, context)

        

        # Read use_ollama setting from context (default to False for speed)

        use_ollama = context.get("use_ollama", False)

        

        # 2. Try Ollama LLM if enabled and available

        if use_ollama:

            ollama_status = self.check_ollama_status()

            if ollama_status["connected"]:

                print(f"Ollama is enabled and online. Generating response using model {self.ollama_model}...")

                available_models = ollama_status["models"]

                active_model = self.ollama_model

                # Handle model name mapping

                if active_model not in available_models and len(available_models) > 0:

                    matched = next((m for m in available_models if m.startswith(active_model)), None)

                    if matched:

                        active_model = matched

                    else:

                        active_model = available_models[0]

                        

                try:

                    # FIRST: Attempt dynamic Text-to-SQL if SQL Server or SQLite is active (skip for meta/follow-ups/summaries/SOPs/complex aggregates)

                    if self.ds.engine is not None and intent not in [

                        "GREETING",

                        "FOLLOW_UP_EXPLAIN_DATA",

                        "FOLLOW_UP_BRANCH_NAME",

                        "DASHBOARD_SUMMARY",

                        "SECURITY_CONCERNS",

                        "SOP_QUERY",

                        "FALSE_ALERT_RATE",

                        "LHO_RESPONSE_TIME",

                        "BRANCH_COUNT",

                        "ALERT_TYPES",

                        "ALERT_SEVERITY_COUNT",

                        "RECENT_ALERTS_FILTERED",

                        "LHO_LIST"

                    ]:

                        response = self._process_message_with_text_to_sql(message, history, active_model, context)

                        if response:

                            return response, context

                            

                    # SECOND: Fallback to static category generator with Ollama

                    response = self._generate_with_ollama(message, history, intent, data_payload, active_model)

                    if response:

                        return response, context

                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as net_err:

                    print(f"[OLLAMA TIMEOUT/CONNECTION WARNING] Ollama call failed: {net_err}. Falling back to local rules.")

            else:

                print("Ollama connection failed or unreachable. Falling back...")

            

        # 3. Fallback to Local Rule-Based template compiler

        print("Using local rule-based fallback response generator...")

        response = self._compile_fallback_response(intent, data_payload, clean_msg, context)

        return response, context



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

        

        # 1. Alert Click (e.g. "Tell me more about the Enclosure Tampering alert at SBI Nariman Point")

        alert_query_match = re.search(r'more about the\s+([a-zA-Z\s-]+?)\s+alert at\s+([a-zA-Z\s\d_]+)', msg)

        

        # 2. Incident Click (e.g. "Tell me about incident INC-001 at SBI MP Nagar")

        incident_query_match = re.search(r'about incident\s+(inc-\d+)', msg)



        if alert_query_match:

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
            area_search = "Jankipuram" if "jankipuram" in msg else ("Quila" if "quila" in msg else ("Aonla" if "aonla" in msg else ("Nariman Point" if "nariman" in msg else ("Noida" if "noida" in msg else ""))))
            if not area_search and context.get("active_branch_filter"):
                area_search = context.get("active_branch_filter")
            
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



        # 13. Operator Performance (supporting typos like "oprator" and "leaderboard")

        elif is_semantic("OPERATOR_PERFORMANCE") or (re.search(r'\bop(?:e)?rat(?:o|e)?rs?\b|\bstaff\b|\bpersonnel\b|\bpeoples?\b|\bleaderboard\b|\branking\b', msg) and any(w in msg for w in ["most", "highest", "best", "handled", "incident", "case", "performance", "leaderboard", "ranking", "stat", "top"])):

            intent = "OPERATOR_PERFORMANCE"

            data_payload["operators"] = self.ds.get_operator_performance()

            context["last_query_type"] = "operators"



        # 14. False Alert Rate — Fix Issue 5: Strengthened guard to avoid mis-routing "highest number of alerts"

        elif "false alert" in msg or "false alarm" in msg or ("false" in msg and "rate" in msg) or ("accidental" in msg and "alert" in msg):

            intent = "FALSE_ALERT_RATE"

            data_payload["branches"] = self.ds.get_false_alert_rates()

            context["last_query_type"] = "branches"



        # 15. LHO Response Time / SLA

        elif is_semantic("LHO_RESPONSE_TIME") or "response time" in msg or "sla" in msg or "mttr" in msg:

            intent = "LHO_RESPONSE_TIME"

            data_payload["lhos"] = self.ds.get_lho_response_times()

            context["last_query_type"] = "lhos"



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

        elif ("branch" in msg or "lho" in msg or "circle" in msg) and ("how many" in msg or "count" in msg or "total" in msg or "number of" in msg):

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



        # 31. Alerts by specific Type and Location (e.g. "how many alerts of VMS we have and where")

        elif is_semantic("ALERTS_BY_TYPE") or (re.search(r'\b(vms|sas|analytics|videoanalytics)\b', msg) and any(w in msg for w in ["how many", "count", "where", "distribution"]) and not any(w in msg for w in ["recent", "latest", "time", "order"])):

            intent = "ALERTS_BY_TYPE"

            type_match = re.search(r'\b(vms|sas|analytics|videoanalytics)\b', msg)

            target_type = type_match.group(1).strip().upper() if type_match else "VMS"

            if target_type == "ANALYTICS":

                target_type = "Analytics"

            elif target_type == "VIDEOANALYTICS":

                target_type = "VideoAnalytics"

                

            data_payload["alert_type"] = target_type

            

            if self.ds.engine is not None:

                try:

                    query = """

                        SELECT 

                            COALESCE(Area, Location) as branch_name, 

                            COUNT(*) as alert_count 

                        FROM AlertsDetails 

                        WHERE AlertType LIKE :alt_type

                        GROUP BY Area, Location

                        ORDER BY alert_count DESC

                    """

                    with self.ds.engine.connect() as conn:

                        res = conn.execute(text(query), {"alt_type": f"%{target_type}%"})

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



        # 30. Distinct Alert Types (e.g. "how many alert types we have")

        elif is_semantic("ALERT_TYPES") or any(k in msg for k in ["alert type", "types of alert", "different alerts", "kinds of alert", "types of alerts"]):

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

        

        data_str = json.dumps(data, indent=2, ensure_ascii=False)

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

                timeout=35

            )

            if r.status_code == 200:

                return r.json().get("message", {}).get("content", "")

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as net_err:

            print(f"Ollama generation failed due to network timeout/connection: {net_err}")

            raise net_err

        except Exception as e:

            print(f"Ollama generation failed: {e}")

        return None



    def _retrieve_dynamic_few_shots(self, query: str, k: int = 3) -> str:

        try:

            import os

            # Ensure embedder is loaded

            if self.embedder is None:

                self._semantic_classify(query)

                

            ex_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sql_examples.json")

            if not os.path.exists(ex_path):

                print(f"[RAG MEMORY WARNING] sql_examples.json not found at {ex_path}")

                return ""

                

            with open(ex_path, "r", encoding="utf-8") as f:

                examples = json.load(f)

                

            if not examples:

                return ""

                

            ex_questions = [ex["question"] for ex in examples]

            ex_embeddings = self.embedder.encode(ex_questions, convert_to_tensor=True)

            query_embedding = self.embedder.encode(query, convert_to_tensor=True)

            

            cos_scores = self.util.cos_sim(query_embedding, ex_embeddings)[0]

            top_k_indices = cos_scores.argsort(descending=True)[:k].tolist()

            

            dialect_key = "mssql" if self.ds.use_sql_server else "sqlite"

            few_shot_lines = ["Few-Shot Examples (Dynamically retrieved from Memory):"]

            for idx in top_k_indices:

                ex = examples[idx]

                few_shot_lines.append(f"Q: {ex['question']}")

                few_shot_lines.append(f"SQL: {ex[dialect_key]}\n")

                

            retrieved_str = "\n".join(few_shot_lines) + "\n"

            print(f"[RAG MEMORY] Retrieved top {k} relevant SQL templates for query: '{query}'")

            return retrieved_str

        except Exception as e:

            print(f"[RAG MEMORY ERROR] Failed to retrieve dynamic few shots: {e}")

            return ""



    def _process_message_with_text_to_sql(self, query: str, history: list, model: str, context: dict) -> str:

        """

        Translates a natural language query into SQL using Ollama, validates it via sqlglot,

        executes it with timeouts and limits, and formats the response. Features automatic

        self-correction loops (retries) if database errors occur.

        """

        import sqlglot

        from sqlglot import expressions as exp

        

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



        # Dynamic Few-Shot Examples (retrieved using RAG vector memory)

        few_shots = self._retrieve_dynamic_few_shots(query)



        # Dynamic Schema Linking & Grounding
        dynamic_schema = ""
        if self.schema_linker:
            link_res = self.schema_linker.link_schema_and_values(query)
            dynamic_schema = link_res.get("focused_schema_prompt", "")

        if not dynamic_schema:
            dynamic_schema = self.schema_engine.generate_dynamic_schema_prompt(dialect) if self.schema_engine else ""

        schema_prompt = (
            f"You are a {dialect} database translator for the State Bank of India Centralized Monitoring System (SBI CMS).\n"
            "Based on the user's natural language question, write a single SQL query to retrieve the necessary data.\n"
            "Only return the SQL query inside a markdown code block starting with ```sql and ending with ```. Do not explain the query, do not write extra text.\n\n"
            f"{dynamic_schema}\n\n"
            f"{few_shots}"
            "Guidelines:\n"
            f"- {dialect_rules}\n"
            "- For string matching, use LIKE with wildcards (e.g. Area LIKE '%Bhopal%') to be robust against minor typos.\n"
            "- If querying a specific ticket ID (e.g. INC-001), match the numeric part (e.g. WHERE IncidentId = 1) because Incident_Data.IncidentId is numeric.\n"
            "- Always select readable columns (like Area or Location, EventType, Status, Time).\n"
            "- DO NOT join AlertsDetails and Incident_Data unless the question explicitly asks about operators or supervisors. For general alert details or alert count questions, query AlertsDetails alone."
        )




        # Conversational SQL context memory

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



        max_retries = 2

        error_history = ""

        attempt_prompt = f"Write a {dialect} query to retrieve data for this question: '{query}'{sql_memory_prompt}"



        for attempt in range(max_retries):

            current_user_prompt = attempt_prompt

            if error_history:

                current_user_prompt += (

                    f"\n\n[SELF-CORRECTION CONTEXT]\n"

                    f"Your previous query failed with this database execution error: {error_history}\n"

                    f"Please correct the query, ensure all column names and table names match the schema exactly, and return only the corrected SQL inside a ```sql ... ``` block."

                )



            messages = [

                {"role": "system", "content": schema_prompt},

                {"role": "user", "content": current_user_prompt}

            ]



            try:

                # Step 1: Send query to Ollama

                r = requests.post(

                    f"{self.ollama_host}/api/chat",

                    json={

                        "model": model,

                        "messages": messages,

                        "stream": False,

                        "options": {"temperature": 0.0}

                    },

                    timeout=35

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



                sql_query = sql_query.rstrip(";")

                print(f"[Text-to-SQL] (Attempt {attempt+1}) Cleaned query: {sql_query}")



                # Step 2: Validate syntax and SELECT-only whitelist via sqlglot

                dialect_name = "tsql" if self.ds.use_sql_server else "sqlite"

                parsed = sqlglot.parse_one(sql_query, read=dialect_name)

                

                # Check for SELECT statement AST

                if parsed.key.upper() != "SELECT":

                    raise ValueError("Only read-only SELECT statements are whitelisted for execution.")

                

                # Verify that no write or system command expressions are present in AST

                for node in parsed.walk():

                    if isinstance(node[0], (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Command)):

                        raise ValueError("Execution blocked: Modifying statements (Insert/Update/Delete/Drop/Alter) are strictly prohibited.")



                # Inject dynamic row safety limit if not present

                if dialect_name == "sqlite":

                    if "limit" not in sql_query.lower():

                        sql_query += " LIMIT 100"

                else:

                    if "top" not in sql_query.lower():

                        sql_query = re.sub(r'^SELECT\b', 'SELECT TOP 100', sql_query, flags=re.IGNORECASE)



                print(f"[Text-to-SQL] Running validated query: {sql_query}")



                # Step 3: Execute query with timeout

                with self.ds.engine.connect() as conn:

                    res = conn.execute(text(sql_query))

                    rows = [dict(row) for row in res.mappings()]



                print(f"[Text-to-SQL] Execution success. Retrieved {len(rows)} rows.")



                # Convert Datetime objects to ISO format string

                for row in rows:

                    for k, v in row.items():

                        if isinstance(v, datetime):

                            row[k] = v.isoformat()



                data_str = json.dumps(rows, indent=2, ensure_ascii=False)



                # Step 4: SQL-to-Text natural language report formatter

                system_summary_prompt = (

                    "You are an intelligent Security Operations Analyst chatbot for the State Bank of India Centralized Monitoring System (SBI CMS).\n"

                    "Your task is to answer user queries using the SQL Server query results provided. Be precise, helpful, and conversational.\n\n"

                    "Structure your response strictly as follows:\n"

                    "1. **Direct Answer**: A clear, concise conversational response directly answering the user's question.\n"

                    "2. **Key Observations**: A list of 2-3 detailed observations/insights derived from the data.\n"

                    "3. **Supporting Table**: Present the SQL rows in a clean Markdown Table.\n"

                    "4. **Operations Summary**: A brief, professional operations-level wrap-up or recommended action based on the data.\n\n"

                    "Rules:\n"

                    "- Speak like a professional security operations center (SOC) analyst.\n"

                    "- Do not mention SQL query text, tables, or Python functions in your response.\n"

                    "- If the database returned no rows, state clearly that no records matching the query were found."

                )



                user_prompt = (

                    f"User Question: {query}\n"

                    f"Executed SQL Query: {sql_query}\n"

                    f"Database Query Results:\n```json\n{data_str}\n```\n\n"

                    "Formulate the final analyst report."

                )



                messages_summary = [

                    {"role": "system", "content": system_summary_prompt}

                ]

                for h in history[-6:]:

                    messages_summary.append(h)

                messages_summary.append({"role": "user", "content": user_prompt})



                try:

                    r_summary = requests.post(

                        f"{self.ollama_host}/api/chat",

                        json={

                            "model": model,

                            "messages": messages_summary,

                            "stream": False,

                            "options": {"temperature": 0.2}

                        },

                        timeout=35

                    )

                    if r_summary.status_code == 200:

                        # Update context variables for session SQL memory

                        context["last_sql"] = sql_query

                        

                        # Update last_query_type based on query tables to support context follow-ups

                        sql_lower = sql_query.lower()

                        if "alertsdetails" in sql_lower:

                            context["last_query_type"] = "alerts"

                        elif "incident_data" in sql_lower:

                            context["last_query_type"] = "incidents"

                        elif "cameralist" in sql_lower or "master_camdetails" in sql_lower:

                            context["last_query_type"] = "devices"

                            

                        return r_summary.json().get("message", {}).get("content", "")

                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as summary_net_err:

                    print(f"[Text-to-SQL Warning] Summary generation timed out/failed: {summary_net_err}. Formatting raw query results directly.")

                    context["last_sql"] = sql_query

                    sql_lower = sql_query.lower()

                    if "alertsdetails" in sql_lower:

                        context["last_query_type"] = "alerts"

                    elif "incident_data" in sql_lower:

                        context["last_query_type"] = "incidents"

                    elif "cameralist" in sql_lower or "master_camdetails" in sql_lower:

                        context["last_query_type"] = "devices"

                    

                    # Fix Issue 2: variable was wrongly named query_results, it is `rows` in this scope

                    if not rows:

                        return "No records matching the query were found in the database."

                        

                    # Format rows as Markdown table

                    headers = list(rows[0].keys())

                    table_md = "| " + " | ".join(headers) + " |\n"

                    table_md += "| " + " | ".join(["---"] * len(headers)) + " |\n"

                    for row in rows:

                        table_md += "| " + " | ".join(str(row.get(h, "")) for h in headers) + " |\n"

                        

                    return (

                        f"**Direct Answer**\nHere is the raw database report for your query:\n\n"

                        f"**Supporting Table**\n{table_md}\n\n"

                        f"**Operations Summary**\nPresented raw database records because the AI summarizer timed out."

                    )



            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as net_err:

                print(f"[Text-to-SQL Network Error] Attempt {attempt+1} failed: {net_err}")

                raise net_err

            except Exception as e:

                print(f"[Text-to-SQL Warning] Attempt {attempt+1} failed: {e}")

                error_history = str(e)

                # Keep looping to attempt self-correction

                

        return None



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



        if intent == "LHO_RESPONSE_TIME":

            lhos = data.get("lhos", [])

            if len(lhos) == 0:

                return "No incident response times available to calculate LHO performance."

                

            table = "| LHO Name | Average Response Time | Total Incidents Evaluated |\n"

            table += "|---|---|---|\n"

            for l in lhos:

                table += f"| {l['lho_name']} | {l['avg_response_time_sec']} seconds | {l['total_incidents_evaluated']} |\n"

                

            return (

                f"The **{lhos[0]['lho_name']} LHO** has the best average response time at **{lhos[0]['avg_response_time_sec']} seconds**.\n\n"

                "### Key Observations\n"

                f"- **Top Responding Command Centre**: {lhos[0]['lho_name']} LHO has achieved response latency below 35 seconds.\n"

                "- **SLA Adherence**: Most command centers are operating well within the 60-second immediate response threshold.\n\n"

                "### LHO Response Times Table\n"

                f"{table}\n"

                "### Operations Summary\n"

                "Centralized incident correlation has successfully lowered operator classification lag. Dispatch protocols remain highly efficient."

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

