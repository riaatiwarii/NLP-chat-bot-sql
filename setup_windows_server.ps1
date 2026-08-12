# ==============================================================================
# SBI CMS Central Gateway Server - Windows Setup & Auto-Start Script
# Configures Windows Task Scheduler & Firewall for 24/7 Unattended Hosting
# ==============================================================================

# Ensure script is running with Administrator privileges
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "[ERROR] This setup script requires Administrator privileges!" -ForegroundColor Red
    Write-Host "Please right-click PowerShell and select 'Run as Administrator', then run this script again." -ForegroundColor Yellow
    Exit 1
}

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  SBI CMS Central Gateway Server - Windows 24/7 Setup" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

# Resolve absolute path to run_backend.bat
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$batPath = Join-Path $scriptDir "run_backend.bat"

if (-not (Test-Path $batPath)) {
    Write-Host "[ERROR] Could not locate run_backend.bat at $batPath!" -ForegroundColor Red
    Exit 1
}

Write-Host "[1/3] Path to launcher script: $batPath" -ForegroundColor Green

# ------------------------------------------------------------------------------
# 1. Configure Windows Task Scheduler (Unattended Boot Mode)
# ------------------------------------------------------------------------------
$taskName = "SbiCmsGatewayTask"
$taskDescription = "SBI CMS Chatbot Central Gateway 24/7 Service (Runs at boot without user login)"

Write-Host "[2/3] Registering Windows Scheduled Task '$taskName'..." -ForegroundColor Green

# Action: Run cmd.exe /c run_backend.bat
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`""

# Trigger: At System Startup
$trigger = New-ScheduledTaskTrigger -AtStartup

# Settings: Auto-restart up to 3 times on failure
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

# Principal: NT AUTHORITY\SYSTEM (Runs 24/7 whether user is logged on or not)
$principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\SYSTEM" -LogonType ServiceAccount -RunLevel Highest

# Register or update task
try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $taskDescription -Force | Out-Null
    Write-Host "      [SUCCESS] Scheduled Task '$taskName' registered successfully!" -ForegroundColor Green
    Write-Host "      [NOTE] Task is set to run under NT AUTHORITY\SYSTEM at system boot." -ForegroundColor Yellow
} catch {
    Write-Host "      [ERROR] Failed to register Scheduled Task: $_" -ForegroundColor Red
}

# ------------------------------------------------------------------------------
# 2. Configure Windows Defender Firewall (Inbound Port 8001)
# ------------------------------------------------------------------------------
$fwRuleName = "SBI CMS Chatbot Gateway 8001"

Write-Host "[3/3] Configuring Windows Defender Firewall for Port 8001..." -ForegroundColor Green

$existingRule = Get-NetFirewallRule -DisplayName $fwRuleName -ErrorAction SilentlyContinue

if ($existingRule) {
    Write-Host "      [INFO] Firewall rule '$fwRuleName' already exists." -ForegroundColor Yellow
} else {
    try {
        New-NetFirewallRule -DisplayName $fwRuleName -Direction Inbound -Protocol TCP -LocalPort 8001 -Action Allow | Out-Null
        Write-Host "      [SUCCESS] Allowed Inbound TCP Port 8001 in Windows Firewall." -ForegroundColor Green
    } catch {
        Write-Host "      [ERROR] Failed to create firewall rule: $_" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  Setup Complete! SBI CMS Server is ready for 24/7 operation." -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "To manually start the task now, run:" -ForegroundColor White
Write-Host "  Start-ScheduledTask -TaskName '$taskName'" -ForegroundColor Yellow
Write-Host ""
