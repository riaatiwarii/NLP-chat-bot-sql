# ==============================================================================
# SBI CMS Central Gateway Server - Windows Auto-Start Setup
# Configures Windows Task Scheduler & Firewall for 24/7 Hosting
# ==============================================================================

$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  SBI CMS Central Gateway Server - Windows Auto-Start Setup" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

# Resolve absolute path to project root and run_backend.bat
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$batPath = Join-Path $scriptDir "run_backend.bat"

if (-not (Test-Path $batPath)) {
    Write-Host "[ERROR] Could not locate run_backend.bat at $batPath!" -ForegroundColor Red
    Exit 1
}

Write-Host "[1/3] Project Root: $scriptDir" -ForegroundColor Green
Write-Host "      Launcher Script: $batPath" -ForegroundColor Green

# ------------------------------------------------------------------------------
# 1. Configure Windows Task Scheduler
# ------------------------------------------------------------------------------
$taskName = "SbiCmsGatewayTask"
$taskDescription = "SBI CMS Chatbot Central Gateway 24/7 Background Service"

Write-Host "[2/3] Registering Windows Scheduled Task '$taskName'..." -ForegroundColor Green

# Action: Run cmd.exe /c run_backend.bat with WorkingDirectory set to project root
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`"" -WorkingDirectory $scriptDir

# Trigger: At Startup & Logon
$triggerAtBoot = New-ScheduledTaskTrigger -AtStartup
$triggerAtLogon = New-ScheduledTaskTrigger -AtLogon

# Principal: Target User Profile
if ($isAdmin) {
    Write-Host "      [MODE] Administrator: Registering for user '$env:USERNAME' with Highest Privileges..." -ForegroundColor Yellow
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
} else {
    Write-Host "      [MODE] Standard User: Registering for user '$env:USERNAME'..." -ForegroundColor Yellow
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
}

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)

try {
    # Remove old task if exists
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($triggerAtBoot, $triggerAtLogon) -Settings $settings -Principal $principal -Description $taskDescription -Force | Out-Null
    Write-Host "      [SUCCESS] Scheduled Task '$taskName' registered successfully for '$env:USERNAME'!" -ForegroundColor Green
} catch {
    Write-Host "      [ERROR] Failed to register Scheduled Task: $_" -ForegroundColor Red
}

# ------------------------------------------------------------------------------
# 2. Configure Windows Defender Firewall (Requires Admin)
# ------------------------------------------------------------------------------
$fwRuleName = "SBI CMS Chatbot Gateway 8001"

Write-Host "[3/3] Configuring Windows Defender Firewall for Port 8001..." -ForegroundColor Green

if ($isAdmin) {
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
} else {
    Write-Host "      [INFO] Skipping Firewall rule creation (requires Admin privileges). Local port 8001 works on localhost." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  Setup Complete! Starting task '$taskName' now..." -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

try {
    Start-ScheduledTask -TaskName $taskName
    Write-Host "[SUCCESS] Task '$taskName' started in background!" -ForegroundColor Green
} catch {
    Write-Host "[INFO] To start task manually: Start-ScheduledTask -TaskName '$taskName'" -ForegroundColor Yellow
}
