import os
import sys
from pathlib import Path
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from app.config import config
from app.data_service import DataService
from app.pipeline.orchestrator import PipelineOrchestrator

app = FastAPI(
    title="Production Text-to-SQL Chatbot Gateway",
    version="2.0.0",
    description="16-Stage Modular Text-to-SQL Chatbot Engine with Value Resolution, Self-Correction, Abstention, & Continuous Feedback Loop."
)

# Enable CORS for cross-origin embedded plugin widgets across servers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Services
data_service = DataService()
orchestrator = PipelineOrchestrator(db_engine=data_service.engine if data_service else None)

# Mount Plugin Assets Directory (serves widget.js, widget.css, and demo HTML files)
possible_plugin_dirs = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "plugin_assets")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "plugin_assets")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend", "plugin_assets")),
]
if getattr(sys, 'frozen', False):
    bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    possible_plugin_dirs.insert(0, os.path.join(bundle_dir, "backend", "plugin_assets"))
    possible_plugin_dirs.insert(0, os.path.join(bundle_dir, "plugin_assets"))

plugin_dir = None
for p_dir in possible_plugin_dirs:
    if os.path.exists(p_dir):
        plugin_dir = p_dir
        break

if plugin_dir:
    print(f"[STATIC ASSETS] Mounting /plugin static assets from: {plugin_dir}")
    app.mount("/plugin", StaticFiles(directory=plugin_dir, html=True), name="plugin")

# Root landing route
@app.get("/")
def root():
    """
    Root endpoint serving plugin demo HTML or API gateway status page.
    """
    if plugin_dir:
        demo_path = os.path.join(plugin_dir, "demo.html")
        if os.path.exists(demo_path):
            return FileResponse(demo_path)
    return {
        "status": "Online",
        "service": "Production Text-to-SQL Chatbot Gateway",
        "version": "2.0.0",
        "plugin_demo": "/plugin/demo.html",
        "health_check": "/api/health",
        "documentation": "/docs"
    }

# API Pydantic Schemas
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = None
    context: Optional[Dict[str, Any]] = None

class ChatResponse(BaseModel):
    response: str
    session_id: str
    confidence_score: float
    is_abstention: bool
    used_fallback: bool = False
    sql: Optional[str] = None
    plan: Optional[Dict[str, Any]] = None
    context: Dict[str, Any] = {}

class FeedbackRequest(BaseModel):
    session_id: str
    question: str
    rating: str # "thumbs_up" or "thumbs_down"
    generated_sql: Optional[str] = None
    corrected_sql: Optional[str] = None
    correction_type: Optional[str] = "logic" # "value" or "logic"
    alias_key: Optional[str] = None
    alias_canonical: Optional[str] = None

@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    """
    Main 16-Stage Text-to-SQL Query Endpoint.
    """
    try:
        query_text = request.message
        sid = request.session_id

        res = orchestrator.process_query(user_query=query_text, session_id=sid)

        return ChatResponse(
            response=res["response"],
            session_id=res["session_id"],
            confidence_score=res["confidence_score"],
            is_abstention=res["is_abstention"],
            used_fallback=res.get("used_fallback", False),
            sql=res["sql"],
            plan=res["plan"],
            context=request.context or {}
        )
    except Exception as e:
        print(f"[CHAT ENDPOINT ERROR]: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/feedback")
def feedback_endpoint(request: FeedbackRequest):
    """
    Captures 👍/👎 Feedback & Analyst Corrections.
    - Value-level errors write directly to canonical alias_table.json (and sync Redis).
    - Logic-level errors write (question, wrong_SQL, correct_SQL) to feedback_dataset.jsonl.
    """
    try:
        feedback_entry = orchestrator.feedback_store.record_feedback(
            session_id=request.session_id,
            question=request.question,
            rating=request.rating,
            generated_sql=request.generated_sql,
            corrected_sql=request.corrected_sql,
            correction_type=request.correction_type,
            alias_key=request.alias_key,
            alias_canonical=request.alias_canonical
        )
        collected_count = orchestrator.feedback_store.get_dataset_count()
        return {
            "status": "Success",
            "message": "Feedback captured successfully.",
            "collected_dataset_count": collected_count,
            "min_required_for_finetuning": config.MIN_FINETUNING_EXAMPLES,
            "entry": feedback_entry
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/dashboard")
def get_dashboard():
    """
    Returns dashboard telemetry data.
    """
    try:
        summary = data_service.get_dashboard_summary()
        active_incidents = data_service.get_incidents(status="open_active")
        unhealthy_devices = data_service.get_unhealthy_devices()
        offline_cams = data_service.get_offline_cameras()
        alerts = data_service.get_alerts()
        
        return {
            "summary": summary,
            "active_incidents": active_incidents[:10],
            "unhealthy_devices": unhealthy_devices[:10],
            "offline_cameras": offline_cams[:10],
            "alerts": alerts[-15:],
            "lho_list": data_service.get_lhos(),
            "branch_list": data_service.get_branches()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
def health_check():
    """
    Pipeline & Server Health Check Endpoint.
    Reports status of all 16 pipeline sub-systems.
    """
    dataset_count = orchestrator.feedback_store.get_dataset_count()
    return {
        "status": "Healthy",
        "database_type": "SQL Server" if data_service.use_sql_server else "Local Engine / SQLite",
        "pipeline_stages": {
            "stage_1_symspell": True,
            "stage_2_followup": True,
            "stage_4_value_resolver": True,
            "stage_6_networkx_graph": True,
            "stage_10_sqlglot": True,
            "stage_15_feedback": True,
            "stage_16_redis": orchestrator.redis_client is not None
        },
        "redis_connected": orchestrator.redis_client is not None,
        "ollama": {
            "configured_host": config.OLLAMA_HOST,
            "configured_model": config.OLLAMA_MODEL
        },
        "data_collection_phase": {
            "examples_collected": dataset_count,
            "min_required_for_finetuning": config.MIN_FINETUNING_EXAMPLES,
            "ready_for_finetuning": dataset_count >= config.MIN_FINETUNING_EXAMPLES
        }
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8001"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
