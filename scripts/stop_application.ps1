# ==============================================================================
# AaharaLens -- Safe Application Shutdown Script
# Terminates running backend and frontend processes gracefully.
# Never deletes local storage, Qdrant vectors, databases, or cache directories.
# ==============================================================================

$ErrorActionPreference = "Continue"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " AaharaLens -- Safe Application Shutdown" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$Ports = @(8000, 8501)
$TerminatedCount = 0

foreach ($Port in $Ports) {
    $Connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
    if ($Connections) {
        $Pids = $Connections.OwningProcess | Select-Object -Unique
        foreach ($PidToKill in $Pids) {
            try {
                $Proc = Get-Process -Id $PidToKill -ErrorAction Stop
                Write-Host "[INFO] Stopping process '$($Proc.ProcessName)' (PID: $PidToKill) listening on port $Port..." -ForegroundColor Yellow
                Stop-Process -Id $PidToKill -Force
                $TerminatedCount++
                Write-Host "[OK] Process $PidToKill stopped successfully." -ForegroundColor Green
            } catch {
                Write-Host "[WARNING] Could not terminate process PID $($PidToKill) - $_" -ForegroundColor Red
            }
        }
    } else {
        Write-Host "[INFO] No process listening on port $Port." -ForegroundColor Gray
    }
}

if ($TerminatedCount -gt 0) {
    Write-Host ""
    Write-Host "[SUCCESS] AaharaLens application processes stopped safely." -ForegroundColor Green
    Write-Host "[NOTE] All persistent local storage (Qdrant, JSON DocumentStore, models) remains intact." -ForegroundColor Cyan
} else {
    Write-Host ""
    Write-Host "[INFO] No active AaharaLens processes found." -ForegroundColor Gray
}
