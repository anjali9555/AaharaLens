# ==============================================================================
# AaharaLens -- Windows-Native Frontend Startup Script
# Runs Streamlit UI dashboard connecting to the FastAPI backend.
# No Docker or WSL required.
# ==============================================================================

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " AaharaLens -- Streamlit Frontend Launcher (Windows-Native)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Verify Python Virtual Environment
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonPath)) {
    Write-Host "[ERROR] Virtual environment not found at: $PythonPath" -ForegroundColor Red
    exit 1
}

# 2. Check if Port 8501 is already in use
$Port = 8501
$ActiveConn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
if ($ActiveConn) {
    $ConflictingPid = $ActiveConn.OwningProcess | Select-Object -First 1
    Write-Host "[ERROR] Port $Port is already in use by process PID $ConflictingPid." -ForegroundColor Red
    Write-Host "To stop the existing process, run:" -ForegroundColor Yellow
    Write-Host "  Stop-Process -Id $ConflictingPid -Force" -ForegroundColor Yellow
    exit 1
}

# 3. Check if Backend is reachable
$BackendPort = 8000
$BackendConn = Get-NetTCPConnection -LocalPort $BackendPort -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
if (-not $BackendConn) {
    Write-Host "[WARNING] FastAPI backend on port $BackendPort does not appear to be running." -ForegroundColor Yellow
    Write-Host "Start the backend in another PowerShell terminal using:" -ForegroundColor Yellow
    Write-Host "  .\scripts\start_backend.ps1" -ForegroundColor Yellow
}

Write-Host "[INFO] Starting Streamlit dashboard on http://127.0.0.1:8501" -ForegroundColor Green

# 4. Launch Streamlit
& $PythonPath -m streamlit run app.py --server.port $Port --server.address 127.0.0.1
