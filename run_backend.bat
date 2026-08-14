@echo off
title SBI CMS Chatbot Central Gateway Server
echo ========================================================
echo   SBI CMS Central Gateway Server - Starting...
echo ========================================================

:: Change working directory to project root
cd /d "%~dp0"

:: Check if virtual environment exists
if exist "backend\.venv\Scripts\python.exe" (
    echo [INFO] Virtual environment found. Starting Uvicorn server on port 8001...
    backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8001
) else (
    echo [INFO] Virtual environment not found. Fallback to global python...
    python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8001
)

