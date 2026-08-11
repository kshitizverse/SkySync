# T-Drive Windows PowerShell Startup Script
# Starts the Flask server, waits for readiness, and opens the browser.

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot
$Url = 'http://127.0.0.1:5000'

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host '  T-Drive - Telegram Cloud Storage Launcher' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ''

try {
  $PythonVersion = python --version 2>&1
  Write-Host "[OK] Python detected: $PythonVersion" -ForegroundColor Green
}
catch {
  Write-Host '[ERROR] Python not found. Please install Python 3.8+.' -ForegroundColor Red
  Write-Host '        Download: https://www.python.org/downloads/' -ForegroundColor Yellow
  Read-Host 'Press Enter to exit'
  exit 1
}

Write-Host ''

$RequirementsOk = $false
try {
  python -m pip show flask 2>&1 | Out-Null
  $RequirementsOk = $true
}
catch {
  $RequirementsOk = $false
}

if (-not $RequirementsOk) {
  Write-Host '[INFO] Installing dependencies...' -ForegroundColor Yellow
  python -m pip install -r requirements.txt

  if ($LASTEXITCODE -ne 0) {
    Write-Host '[ERROR] Failed to install dependencies.' -ForegroundColor Red
    Read-Host 'Press Enter to exit'
    exit 1
  }

  Write-Host '[OK] Dependencies installed.' -ForegroundColor Green
  Write-Host ''
}

Write-Host '[INFO] Starting T-Drive server...' -ForegroundColor Green
Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host '   Server Status:' -ForegroundColor Cyan
Write-Host '   URL:     http://127.0.0.1:5000' -ForegroundColor White
Write-Host '   Login:   Telegram OTP login via your phone number' -ForegroundColor White
Write-Host '   Close:   Stop the Python process manually if needed' -ForegroundColor White
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ''

$existing = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique

if ($existing) {
  Write-Host "[WARN] Port 5000 is already in use. Stopping old process(es): $($existing -join ', ')" -ForegroundColor Yellow
  $existing | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 1
}

$pythonw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
  $pythonw = (Get-Command python -ErrorAction Stop).Source
}

$stdoutLog = Join-Path $ProjectRoot 'server.stdout.log'
$stderrLog = Join-Path $ProjectRoot 'server.stderr.log'
if (Test-Path $stdoutLog) { Remove-Item $stdoutLog -Force -ErrorAction SilentlyContinue }
if (Test-Path $stderrLog) { Remove-Item $stderrLog -Force -ErrorAction SilentlyContinue }

$process = Start-Process `
  -FilePath $pythonw `
  -ArgumentList 'main.py' `
  -WorkingDirectory $ProjectRoot `
  -RedirectStandardOutput $stdoutLog `
  -RedirectStandardError $stderrLog `
  -PassThru
$ready = $false

for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 1

  if ($process.HasExited) {
    Write-Host '[ERROR] T-Drive exited before startup completed. Check app.log for details.' -ForegroundColor Red
    break
  }

  try {
    $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 2
    if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
      $ready = $true
      break
    }
  }
  catch {
  }
}

if ($ready) {
  Write-Host '[OK] T-Drive is running. Opening browser...' -ForegroundColor Green
  Start-Process $Url | Out-Null
}
else {
  Write-Host '[ERROR] T-Drive did not become ready in time. Check app.log.' -ForegroundColor Red
}

Write-Host ''
Write-Host "Server PID: $($process.Id)" -ForegroundColor DarkGray
Write-Host "Stdout log: $stdoutLog" -ForegroundColor DarkGray
Write-Host "Stderr log: $stderrLog" -ForegroundColor DarkGray
Read-Host 'Press Enter to exit'
