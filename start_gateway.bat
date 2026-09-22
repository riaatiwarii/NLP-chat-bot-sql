@echo off
title SBI CMS Chatbot AI Gateway Service
color 0A

echo ====================================================================
echo             SBI CMS CENTRALIZED MONITORING CHATBOT GATEWAY          
echo ====================================================================
echo.

:: Set environment variables (or override defaults if needed)
if exist "%~dp0dist\SbiCmsGateway\.env" (
    echo [CONFIG] Loading custom environment configuration from .env file...
    for /f "tokens=*" %%i in ('type "%~dp0dist\SbiCmsGateway\.env"') do set "%%i"
) else (
    echo [CONFIG] WARNING: No .env file found - create one with DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, OLLAMA_HOST before running.
)

echo.
echo [SERVER] Launching SbiCmsGateway.exe...
echo [ENDPOINT] Gateway API active at: http://localhost:8001
echo.

"%~dp0dist\SbiCmsGateway\SbiCmsGateway.exe"

pause
