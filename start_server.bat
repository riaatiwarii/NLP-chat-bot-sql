@echo off
title SBI CMS Central Gateway Server
echo ========================================================
echo   SBI CMS Central Gateway Server - Service Launcher
echo ========================================================
echo.

cd /d "%~dp0"

echo [1/2] Opening Firewall Port 8001 for Client Network Connections...
netsh advfirewall firewall add rule name="SBI_CMS_Gateway_8001" dir=in action=allow protocol=TCP localport=8001 >nul 2>&1

echo [2/2] Launching Central Gateway Server Executable...
echo.
echo Server IP Details:
ipconfig | findstr /i "IPv4"
echo.
echo ====================================================================
echo  Integrate this plugin script into any HTML portal on client systems:
echo.
echo  ^<script 
echo    src="http://YOUR_SERVER_IP:8001/plugin/widget.js" 
echo    data-sbi-cms-gateway="http://YOUR_SERVER_IP:8001" 
echo    data-theme="dark" 
echo    data-position="bottom-right"^^>
echo  ^</script^^>
echo ====================================================================
echo.

if exist "dist\SbiCmsGateway\SbiCmsGateway.exe" (
    "dist\SbiCmsGateway\SbiCmsGateway.exe"
) else (
    echo [ERROR] Executable dist\SbiCmsGateway\SbiCmsGateway.exe not found!
    echo Please run build_exe.bat first to compile the package.
    pause
)
