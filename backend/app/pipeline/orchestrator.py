import uuid
from sentence_transformers import SentenceTransformer
from sqlalchemy import Engine, inspect, text

from app.config import config
from app.pipeline.input_normalizer import InputNormalizer
from app.pipeline.followup_detector import FollowupDetector
from app.pipeline.extractor import Extractor
from app.pipeline.value_resolver import ValueResolver
from app.pipeline.intent_resolver import IntentResolver
from app.pipeline.schema_graph import SchemaGraph
from app.pipeline.plan_generator import PlanGenerator
from app.pipeline.plan_validator import PlanValidator
from app.pipeline.sql_generator import SQLGenerator
from app.pipeline.sql_validator import SQLValidator
from app.pipeline.self_correction import SelfCorrectionLoop
from app.pipeline.confidence_scorer import ConfidenceScorer
from app.pipeline.executor import SQLExecutor
from app.pipeline.response_synthesizer import ResponseSynthesizer
from app.pipeline.feedback_store import FeedbackStore
from app.pipeline.session_memory import SessionMemory

class PipelineOrchestrator:
    """
    Master 16-Stage Text-to-SQL Pipeline Orchestrator.
    Encapsulates stages 1 to 16 in strict execution sequence.
    """
    def __init__(self, db_engine: Engine = None):
        self.db_engine = db_engine
        
        # Redis client connection (optional gracefully failing cache)
        self.redis_client = self._init_redis()

        # Shared embedding model
        print("[PIPELINE ORCHESTRATOR] Loading shared embedding model (all-MiniLM-L6-v2)...", flush=True)
        try:
            self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception as e:
            print(f"[PIPELINE ORCHESTRATOR WARNING] Could not load SentenceTransformer: {e}", flush=True)
            self.embedder = None

        # Introspect DB schema & distinct sample values
        self.tables_schema, self.distinct_db_values, self.fk_edges = self._introspect_schema()

        # Initialize Pipeline Components (Stages 1-16)
        schema_terms = list(self.tables_schema.keys())
        for cols in self.tables_schema.values():
            for c in cols:
                col_name = c["name"] if isinstance(c, dict) else str(c)
                schema_terms.append(col_name)

        self.normalizer = InputNormalizer(schema_terms=schema_terms) # Stage 1
        self.followup_detector = FollowupDetector(embedder=self.embedder) # Stage 2
        self.extractor = Extractor() # Stage 3
        self.value_resolver = ValueResolver(
            distinct_db_values=self.distinct_db_values,
            embedder=self.embedder,
            redis_client=self.redis_client
        ) # Stage 4
        self.intent_resolver = IntentResolver() # Stage 5
        self.schema_graph = SchemaGraph(
            tables_schema=self.tables_schema,
            fk_edges=self.fk_edges,
            embedder=self.embedder
        ) # Stage 6
        self.plan_generator = PlanGenerator() # Stage 7
        self.plan_generator.validate_schema_integrity({"tables": self.tables_schema})
        self.plan_validator = PlanValidator(schema_graph=self.schema_graph) # Stage 8
        self.sql_generator = SQLGenerator() # Stage 9
        self.sql_validator = SQLValidator(db_engine=self.db_engine) # Stage 10
        self.self_correction_loop = SelfCorrectionLoop(
            sql_generator=self.sql_generator,
            sql_validator=self.sql_validator
        ) # Stage 11
        self.confidence_scorer = ConfidenceScorer() # Stage 12
        self.executor = SQLExecutor(db_engine=self.db_engine) # Stage 13
        self.response_synthesizer = ResponseSynthesizer(schema_table_names=list(self.tables_schema.keys())) # Stage 14
        self.feedback_store = FeedbackStore(value_resolver=self.value_resolver) # Stage 15
        self.session_memory = SessionMemory(redis_client=self.redis_client) # Stage 16

    def process_query(self, user_query: str, session_id: str = None) -> dict:
        """
        Executes full 16-stage pipeline for a query.
        Returns response dict containing response_text, sql, confidence_score, session_id, and metadata.
        """
        sid = session_id or str(uuid.uuid4())

        # System Intent Interceptor: DASHBOARD_SUMMARY (Option B Layout: Area/Zone Breakdown Table)
        query_low = user_query.lower()
        if any(phrase in query_low for phrase in [
            "dashboard summary", "dashboard overview", "today's dashboard summary",
            "todays dashboard summary", "show today's dashboard summary",
            "system overview", "central dashboard summary"
        ]):
            from app.data_service import DataService
            ds = DataService()
            s = ds.get_dashboard_summary()
            breakdown = s.get("breakdown", [])
            tot_alerts = s.get("total_alerts_count", 0)
            
            tbl = "| Monitored Branch / Area | Total Alerts Registered | Pending Alerts | Closed / Resolved | Share |\n|---|---|---|---|---|\n"
            for item in breakdown:
                tbl += f"| **{item['branch_name']}** | **{item['total_alerts']:,}** | {item['pending_alerts']:,} | {item['closed_alerts']:,} | {item['share_pct']}% |\n"
                
            top_name = breakdown[0]['branch_name'] if breakdown else 'N/A'
            top_cnt = breakdown[0]['total_alerts'] if breakdown else 0
            top_pct = breakdown[0]['share_pct'] if breakdown else 0
            
            resp_text = (
                f"Alert breakdown grouped by **Monitored Branch / Area** (total **{tot_alerts:,} alerts** across **{len(breakdown)} categories**):\n\n"
                f"### Security Alerts Grouped by Monitored Branch / Area\n{tbl}\n"
                f"### Operations Summary\n"
                f"Highest category: **{top_name}** representing **{top_cnt:,} alerts** (`{top_pct}%` share of volume)."
            )
            self.session_memory.add_turn(sid, user_query, {"intent": "DASHBOARD_SUMMARY"}, "N/A (System Telemetry Summary)", resp_text[:200])
            return {
                "response": resp_text,
                "sql": "N/A (System Telemetry Summary)",
                "plan": {"intent": "DASHBOARD_SUMMARY", "tables_needed": ["AlertsDetails"]},
                "confidence_score": 1.0,
                "is_abstention": False,
                "used_fallback": False,
                "session_id": sid,
                "rows_count": len(breakdown)
            }

        # STAGE 1: Input Normalization (spell correction)
        normalized_query = self.normalizer.normalize(user_query)

        # STAGE 2: Follow-up Detection
        prior_turn = self.session_memory.get_last_turn(sid)
        prior_query = prior_turn.get("question") if prior_turn else None
        prior_plan = prior_turn.get("plan") if prior_turn else None
        
        is_followup, sim_score = self.followup_detector.is_followup(normalized_query, prior_query)

        # STAGE 3: Intent + Entity Extraction
        spans_dict = self.extractor.extract(normalized_query)
        entity_spans = spans_dict.get("entity_spans", [])
        intent_spans = spans_dict.get("intent_spans", [])

        # STAGE 4: Value Resolution Cascade
        resolved_entities = []
        for e in entity_spans:
            if e.get("type") in ["date_relative", "date_explicit"]:
                resolved_entities.append({
                    "original_span": e["span"],
                    "resolved_value": e["span"],
                    "matched_column": None,
                    "resolution_step": "date_extraction",
                    "confidence": 1.0,
                    "is_resolved": True,
                    "type": e.get("type")
                })
            else:
                res = self.value_resolver.resolve_entity(e["span"], entity_type=e.get("type"))
                res["type"] = e.get("type")
                resolved_entities.append(res)

        # STAGE 5: Intent-Keyword Resolution
        resolved_intent = self.intent_resolver.resolve_intent(intent_spans, normalized_query)

        # STAGE 6: Schema Linking (top-k NetworkX schema graph subset)
        schema_subset = self.schema_graph.get_relevant_schema_subset(normalized_query)

        # STAGE 7 & 8: Structured Query Plan Generation & Validation Loop
        plan_res = self.plan_generator.generate_plan(
            normalized_query, resolved_entities, resolved_intent, schema_subset,
            prior_plan=prior_plan if is_followup else None,
            is_followup=is_followup
        )
        if isinstance(plan_res, tuple):
            plan, plan_fallback = plan_res
        else:
            plan, plan_fallback = plan_res, False

        plan_valid, plan_err = self.plan_validator.validate(plan)
        if not plan_valid:
            # Stage 8 Retry (max 1 retry with error appended to prompt)
            plan_res = self.plan_generator.generate_plan(
                normalized_query, resolved_entities, resolved_intent, schema_subset,
                prior_plan=prior_plan if is_followup else None,
                is_followup=is_followup,
                validation_error=plan_err
            )
            if isinstance(plan_res, tuple):
                plan, fb2 = plan_res
                plan_fallback = plan_fallback or fb2
            else:
                plan = plan_res

            plan_valid, plan_err = self.plan_validator.validate(plan)

        # STAGE 9, 10, 11: SQL Generation, Validation, & Self-Correction Retry Loop
        sql_query, sql_valid, sql_err, attempts_count, sql_fallback = self.self_correction_loop.execute_with_retry(
            validated_plan=plan,
            schema_subset=schema_subset
        )

        used_fallback = plan_fallback or sql_fallback

        # STAGE 12: Confidence Scoring & Abstention Check
        confidence_score, should_abstain, clarification_msg = self.confidence_scorer.calculate_confidence(
            entities=resolved_entities,
            plan_valid=plan_valid,
            sql_valid=sql_valid,
            attempts_count=attempts_count
        )

        # Abstention Check Decision
        if should_abstain:
            self.feedback_store.log_query(sid, user_query, plan, sql_query, confidence_score, 0)
            return {
                "response": clarification_msg,
                "sql": None,
                "plan": plan,
                "confidence_score": confidence_score,
                "is_abstention": True,
                "used_fallback": used_fallback,
                "session_id": sid
            }

        # STAGE 13: Execute SQL
        rows, column_names, total_count, exec_err = self.executor.execute(sql_query)
        if exec_err and attempts_count < config.MAX_SELF_CORRECTION_ATTEMPTS:
            # Try 1 more execution error self-repair retry
            gen_res = self.sql_generator.generate_sql(plan, schema_subset, retry_error=exec_err)
            if isinstance(gen_res, tuple):
                sql_query, fb3 = gen_res
                used_fallback = used_fallback or fb3
            else:
                sql_query = gen_res
            rows, column_names, total_count, exec_err = self.executor.execute(sql_query)

        # STAGE 14: Natural Language Response Synthesis
        response_text = self.response_synthesizer.synthesize(
            user_query, rows, column_names, total_count=total_count, select_columns=plan.get("select_columns")
        )

        # STAGE 15: Logging & Feedback Capture
        self.feedback_store.log_query(sid, user_query, plan, sql_query, confidence_score, len(rows))

        # STAGE 16: Session Memory Update
        self.session_memory.add_turn(sid, user_query, plan, sql_query, response_text[:200])

        return {
            "response": response_text,
            "sql": sql_query if config.SHOW_GENERATED_SQL else None,
            "plan": plan,
            "confidence_score": confidence_score,
            "is_abstention": False,
            "used_fallback": used_fallback,
            "session_id": sid,
            "rows_count": len(rows)
        }

    def _init_redis(self):
        if not config.REDIS_ENABLED:
            return None
        try:
            import redis
            r = redis.Redis(
                host=config.REDIS_HOST,
                port=config.REDIS_PORT,
                db=config.REDIS_DB,
                password=config.REDIS_PASSWORD or None,
                socket_timeout=2.0
            )
            r.ping()
            print(f"[PIPELINE ORCHESTRATOR] Connected to Redis cache at {config.REDIS_HOST}:{config.REDIS_PORT}", flush=True)
            return r
        except Exception as e:
            print(f"[PIPELINE ORCHESTRATOR INFO] Redis offline/not connected ({e}). Using local in-memory fallback stores.", flush=True)
            return None

    def _introspect_schema(self) -> tuple[dict, dict, list]:
        """Introspects database tables, sample categorical values, and foreign keys."""
        if not self.db_engine:
            return {}, {}, []

        inspector = inspect(self.db_engine)
        tables_schema = {}
        distinct_db_values = {}
        fk_edges = []

        try:
            raw_tables = inspector.get_table_names()
            excluded = ('__', 'sys', 'dtproperties', 'AspNet', 'Log4', 'API_', 'DMS_', 'Token', 'AccessToken')
            if config.ALLOWED_TABLES:
                allowed_lower = [a.lower() for a in config.ALLOWED_TABLES]
                tables = [t for t in raw_tables if t.lower() in allowed_lower]
            else:
                tables = ordered[:25]

            print(f"[DATABASE INTROSPECTION] Introspecting target schema tables ({len(tables)} tables): {tables}...", flush=True)

            dialect = self.db_engine.dialect.name.lower()

            with self.db_engine.connect() as conn:
                for tbl in tables:
                    print(f"  -> Loading schema & column values for '{tbl}'...", flush=True)
                    columns = inspector.get_columns(tbl)
                    tables_schema[tbl] = [{"name": c["name"], "type": str(c["type"])} for c in columns]

                    # Foreign keys
                    fks = inspector.get_foreign_keys(tbl)
                    for fk in fks:
                        target_tbl = fk.get('referred_table')
                        if target_tbl:
                            fk_edges.append((tbl, target_tbl, {"fk": f"{tbl}->{target_tbl}"}))

                    # Sample distinct values for string columns
                    for c in columns:
                        col_name = c["name"]
                        col_type = str(c["type"]).lower()
                        if any(t in col_type for t in ['char', 'text', 'string', 'varchar', 'nvarchar']):
                            if not any(k in col_name.lower() for k in ['id', 'uuid', 'password', 'key', 'guid']):
                                try:
                                    if "mssql" in dialect or "pyodbc" in dialect:
                                        query = text(f"SELECT DISTINCT TOP 30 [{col_name}] FROM [{tbl}] WHERE [{col_name}] IS NOT NULL")
                                    else:
                                        query = text(f"SELECT DISTINCT [{col_name}] FROM [{tbl}] WHERE [{col_name}] IS NOT NULL LIMIT 30")
                                    
                                    res = conn.execute(query).fetchall()
                                    vals = [str(r[0]).strip() for r in res if r[0] is not None and str(r[0]).strip()]
                                    if vals:
                                        distinct_db_values.setdefault(col_name, []).extend(vals)
                                except Exception:
                                    pass

        except Exception as e:
            print(f"[SCHEMA INTROSPECTION WARNING] Introspection error: {e}", flush=True)

        return tables_schema, distinct_db_values, fk_edges
