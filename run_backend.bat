@echo off
title SBI CMS Chatbot Central Gateway Server
echo ========================================================
echo   SBI CMS Central Gateway Server - Starting...
echo ========================================================

cd /d "%~dp0"

if not exist "backend\.venv\Scripts\python.exe" goto GLOBAL_PYTHON

echo [INFO] Virtual environment found. Starting Uvicorn server on port 8001...
call backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8001
goto END

:GLOBAL_PYTHON
echo [INFO] Virtual environment not found. Fallback to global python...
call python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8001

:END
echo.
echo ====================================================================
echo Server execution ended.
pause
