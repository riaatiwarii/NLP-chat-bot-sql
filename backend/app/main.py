import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from app.data_service import DataService
from app.chatbot_service import ChatbotService

app = FastAPI(title="SBI CMS Chatbot Central Gateway Backend", version="1.0.0")

# Enable CORS for cross-origin embedded plugin widgets and web apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allows embedding widget into any bank portal
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Services
data_service = DataService()
chatbot_service = ChatbotService(data_service)

import sys

# Mount Plugin Assets Directory (serves widget.js, widget.css, and demo.html)
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
else:
    print("[STATIC ASSETS WARNING] plugin_assets directory not found!")


# Request / Response Schemas
class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, str]]
    context: Dict[str, Any]

class ChatResponse(BaseModel):
    response: str
    context: Dict[str, Any]
    ollama_active: bool

class SettingsRequest(BaseModel):
    ollama_host: str
    ollama_model: str

@app.get("/api/dashboard")
def get_dashboard():
    """
    Returns aggregated metrics and charts dataset for the operations dashboard.
    """
    try:
        summary = data_service.get_dashboard_summary()
        active_incidents = data_service.get_incidents(status="open_active")
        unhealthy_devices = data_service.get_unhealthy_devices()
        offline_cams = data_service.get_offline_cameras()
        alerts = data_service.get_alerts()
        
        # Format a response payload
        return {
            "summary": summary,
            "active_incidents": active_incidents[:10], # limit to recent 10
            "unhealthy_devices": unhealthy_devices[:10],
            "offline_cameras": offline_cams[:10],
            "alerts": alerts[-15:], # recent 15 alerts
            "lho_list": data_service.get_lhos(),
            "branch_list": data_service.get_branches()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    """
    Core chatbot query endpoint.
    """
    try:
        response_text, updated_context = chatbot_service.process_message(
            message=request.message,
            history=request.history,
            context=request.context
        )
        ollama_status = chatbot_service.check_ollama_status()
        return ChatResponse(
            response=response_text,
            context=updated_context,
            ollama_active=ollama_status["connected"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
def health_check():
    """
    Checks backend service status and tests local Ollama connection.
    """
    ollama_status = chatbot_service.check_ollama_status()
    return {
        "status": "Healthy",
        "database_type": "SQL Server" if data_service.use_sql_server else "Local JSON Failsafe",
        "ollama": {
            "connected": ollama_status["connected"],
            "configured_host": chatbot_service.ollama_host,
            "configured_model": chatbot_service.ollama_model,
            "available_models": ollama_status["models"]
        }
    }

@app.post("/api/settings")
def update_settings(request: SettingsRequest):
    """
    Updates the Ollama host and model configuration in the running backend.
    """
    try:
        chatbot_service.configure_ollama(
            host=request.ollama_host,
            model=request.ollama_model
        )
        return {"status": "Success", "message": "Ollama configurations updated."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # Start the server on port 8000
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
