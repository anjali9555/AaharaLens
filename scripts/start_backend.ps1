# ==============================================================================
# AaharaLens -- Windows-Native Backend Startup Script
# Runs FastAPI backend with single-owner Qdrant persistent storage safety.
# No Docker or WSL required.
# ==============================================================================

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " AaharaLens -- FastAPI Backend Launcher (Windows-Native)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Verify Python Virtual Environment
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonPath)) {
    Write-Host "[ERROR] Virtual environment not found at: $PythonPath" -ForegroundColor Red
    Write-Host "Please create a virtual environment first:" -ForegroundColor Yellow
    Write-Host "  python -m venv .venv" -ForegroundColor Yellow
    Write-Host "  .\.venv\Scripts\pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

# 2. Verify .env file
$EnvPath = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $EnvPath)) {
    Write-Host "[WARNING] .env file not found. Falling back to default configuration." -ForegroundColor Yellow
}

# 3. Check if Port 8000 is already in use
$Port = 8000
$ActiveConn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
if ($ActiveConn) {
    $ConflictingPid = $ActiveConn.OwningProcess | Select-Object -First 1
    Write-Host "[ERROR] Port $Port is already in use by process PID $ConflictingPid." -ForegroundColor Red
    Write-Host "AaharaLens requires single-process ownership of local Qdrant storage." -ForegroundColor Yellow
    Write-Host "To stop the existing process, run:" -ForegroundColor Yellow
    Write-Host "  Stop-Process -Id $ConflictingPid -Force" -ForegroundColor Yellow
    Write-Host "Or use the project shutdown script: .\scripts\stop_application.ps1" -ForegroundColor Yellow
    exit 1
}

# 4. Verify storage directories exist
$StorageDir = Join-Path $ProjectRoot "data\storage\qdrant_data"
if (-not (Test-Path $StorageDir)) {
    New-Item -ItemType Directory -Force -Path $StorageDir | Out-Null
}

Write-Host "[INFO] Starting single-worker FastAPI backend on http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "[INFO] Qdrant local persistence enabled (Single-Owner mode)" -ForegroundColor Green

# 5. Launch Uvicorn with single worker
& $PythonPath -m uvicorn src.main:app --host 127.0.0.1 --port $Port --workers 1
