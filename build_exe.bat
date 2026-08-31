@echo off
title SBI CMS Chatbot - Executable Builder
echo ========================================================
echo   SBI CMS Central Gateway Server - Building Executable
echo ========================================================

cd /d "%~dp0"

echo [1/2] Checking PyInstaller...
backend\.venv\Scripts\pyinstaller.exe --version

echo [2/2] Compiling standalone executable package...
backend\.venv\Scripts\pyinstaller.exe --noconfirm --onedir --name "SbiCmsGateway" --paths "backend" --paths "backend/app" --hidden-import "pymssql" --hidden-import "app" --hidden-import "app.main" --hidden-import "app.data_service" --hidden-import "app.chatbot_service" --hidden-import "app.schema_engine" --hidden-import "app.schema_linker" --hidden-import "app.context_tracker" --add-data "backend/.env;." --add-data "backend/app;app" --add-data "backend/plugin_assets;backend/plugin_assets" launcher.py

echo.
echo ========================================================
echo [SUCCESS] Executable built successfully!
echo Executable Location: dist\SbiCmsGateway\SbiCmsGateway.exe
echo ========================================================
