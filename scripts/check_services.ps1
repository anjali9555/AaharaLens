# ==============================================================================
# AaharaLens -- Service Health and Diagnostics Check Script
# Inspects FastAPI, MongoDB Atlas, Qdrant, BGE FastEmbed, and Cache status.
# ==============================================================================

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " AaharaLens -- Windows-Native Service Diagnostics" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Port Status Check
$BackendPort = 8000
$FrontendPort = 8501

$BackendConn = Get-NetTCPConnection -LocalPort $BackendPort -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
if ($BackendConn) {
    Write-Host "[OK] FastAPI Backend is listening on port $BackendPort (PID: $($BackendConn.OwningProcess | Select-Object -First 1))" -ForegroundColor Green
} else {
    Write-Host "[OFFLINE] FastAPI Backend is NOT running on port $BackendPort" -ForegroundColor Red
}

$FrontendConn = Get-NetTCPConnection -LocalPort $FrontendPort -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
if ($FrontendConn) {
    Write-Host "[OK] Streamlit Frontend is listening on port $FrontendPort (PID: $($FrontendConn.OwningProcess | Select-Object -First 1))" -ForegroundColor Green
} else {
    Write-Host "[OFFLINE] Streamlit Frontend is NOT running on port $FrontendPort" -ForegroundColor Yellow
}

# 2. Query Backend Health API Endpoint
if ($BackendConn) {
    Write-Host ""
    Write-Host "Querying http://127.0.0.1:$BackendPort/health..." -ForegroundColor Cyan
    try {
        $Response = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/health" -Method Get -TimeoutSec 3
        Write-Host ""
        Write-Host "--- APPLICATION HEALTH REPORT ---" -ForegroundColor White
        Write-Host "Service Status   : $($Response.status)" -ForegroundColor Green
        Write-Host "Version          : $($Response.version)" -ForegroundColor Gray
        Write-Host "Environment      : $($Response.environment)" -ForegroundColor Gray
        Write-Host "Runtime          : $($Response.runtime)" -ForegroundColor Gray

        Write-Host ""
        Write-Host "--- DATABASE STATUS ---" -ForegroundColor White
        Write-Host "Backend          : $($Response.database.backend)" -ForegroundColor Yellow
        Write-Host "Database Name    : $($Response.database.database)" -ForegroundColor Gray
        Write-Host "Atlas Connected  : $($Response.database.connected_to_atlas)" -ForegroundColor Gray
        Write-Host "Fallback Active  : $($Response.database.fallback_active)" -ForegroundColor Gray

        Write-Host ""
        Write-Host "--- VECTOR DATABASE AND HYBRID RAG ---" -ForegroundColor White
        Write-Host "RAG Mode         : $($Response.vector_db.rag_mode)" -ForegroundColor Yellow
        Write-Host "Qdrant Mode      : $($Response.vector_db.qdrant_mode)" -ForegroundColor Gray
        Write-Host "Qdrant Healthy   : $($Response.vector_db.qdrant_healthy)" -ForegroundColor Gray
        Write-Host "Embedding Model  : $($Response.vector_db.embedding_model)" -ForegroundColor Gray
        Write-Host "Dimensions       : $($Response.vector_db.embedding_dimensions)" -ForegroundColor Gray
        Write-Host "Chunks Indexed   : $($Response.vector_db.bm25_chunks_indexed)" -ForegroundColor Gray

        Write-Host ""
        Write-Host "--- APPLICATION CACHE ---" -ForegroundColor White
        Write-Host "Cache Mode       : $($Response.cache.mode)" -ForegroundColor Yellow
        Write-Host "Redis Connected  : $($Response.cache.redis_connected)" -ForegroundColor Gray
        Write-Host "Fallback Active  : $($Response.cache.fallback_active)" -ForegroundColor Gray
        Write-Host "In-Memory Items  : $($Response.cache.in_memory_items)" -ForegroundColor Gray
        if ($Response.cache.warning) {
            Write-Host "Note             : $($Response.cache.warning)" -ForegroundColor DarkYellow
        }

        Write-Host ""
        Write-Host "--- AI AND VISION ---" -ForegroundColor White
        Write-Host "Groq Configured  : $($Response.groq_configured)" -ForegroundColor Gray
        Write-Host "LLM Model        : $($Response.groq_model)" -ForegroundColor Gray
    } catch {
        Write-Host "[ERROR] Could not retrieve health status from backend: $_" -ForegroundColor Red
    }
} else {
    Write-Host ""
    Write-Host "Tip: Run .\scripts\start_backend.ps1 to start the application." -ForegroundColor Gray
}
