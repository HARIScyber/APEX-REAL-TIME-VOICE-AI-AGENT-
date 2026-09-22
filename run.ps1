# ==============================================================================
# APEX REAL-TIME VOICE AI AGENT - POWERSHELL LAUNCHER
# ==============================================================================
# Usage:
#   Open PowerShell in this directory and execute:
#     .\run.ps1
#
# What this script does:
#   1. Creates a Python virtual environment (.venv) if one does not exist.
#   2. Activates the virtual environment.
#   3. Installs dependencies from requirements.txt.
#   4. Starts the FastAPI server on http://localhost:8000.
# ==============================================================================

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "                    APEX REAL-TIME VOICE AI AGENT                            " -ForegroundColor Cyan
Write-Host "         AssemblyAI STT + FastAPI Orchestrator + Multi-LLM + TTS              " -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Check and create virtual environment if missing
if (-not (Test-Path ".venv")) {
    Write-Host "[*] Creating Python virtual environment (.venv)..." -ForegroundColor Yellow
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Could not create virtual environment. Ensure Python is installed." -ForegroundColor Red
        Exit 1
    }
}

# Step 2: Activate virtual environment
Write-Host "[*] Activating virtual environment..." -ForegroundColor Green
& .\.venv\Scripts\Activate.ps1

# Step 3: Install dependencies
Write-Host "[*] Checking and installing dependencies from requirements.txt..." -ForegroundColor Yellow
pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to install packages." -ForegroundColor Red
    Exit 1
}

# Step 4: Launch Uvicorn ASGI Server
Write-Host "`n==============================================================================" -ForegroundColor Green
Write-Host "  Server started successfully!" -ForegroundColor Green
Write-Host "  Access Web UI at: http://localhost:8000" -ForegroundColor Cyan
Write-Host "==============================================================================`n" -ForegroundColor Green

python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
