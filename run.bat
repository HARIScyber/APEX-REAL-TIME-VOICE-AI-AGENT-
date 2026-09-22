@echo off
rem ==============================================================================
rem APEX REAL-TIME VOICE AI AGENT - WINDOWS BATCH LAUNCHER
rem ==============================================================================
rem This script automates running the Real-Time Voice Agent on Windows:
rem   1. Checks if a Python virtual environment exists; if not, creates one.
rem   2. Activates the virtual environment.
rem   3. Installs or updates dependencies from requirements.txt.
rem   4. Starts the FastAPI server with live reload on port 8000.
rem ==============================================================================

title Apex Real-Time Voice AI Agent
color 0b
echo ==============================================================================
echo                 APEX REAL-TIME VOICE AI AGENT
echo      AssemblyAI STT + FastAPI Orchestrator + Streaming LLM + TTS
echo ==============================================================================
echo.

rem Step 1: Check for Python virtual environment
if not exist .venv (
    echo [*] Creating virtual environment (.venv)...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment. Ensure Python 3.10+ is installed.
        pause
        exit /b 1
    )
)

rem Step 2: Activate virtual environment
echo [*] Activating virtual environment...
call .venv\Scripts\activate

rem Step 3: Install required Python dependencies
echo [*] Verifying and installing requirements...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install packages. Check internet connection.
    pause
    exit /b 1
)

echo.
echo ==============================================================================
echo   Server is launching!
echo   Open your browser and navigate to: http://localhost:8000
echo ==============================================================================
echo.

rem Step 4: Run FastAPI with Uvicorn
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
pause
