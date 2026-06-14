@echo off
echo ========================================
echo AI Workflow Platform - Quick Start
echo ========================================
echo.

echo [1/4] Checking prerequisites...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Please install Python 3.10+
    pause
    exit /b 1
)

where node >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Node.js not found. Please install Node.js 18+
    pause
    exit /b 1
)

echo Prerequisites OK!
echo.

echo [2/4] Setting up backend...
cd backend
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Installing Python dependencies...
pip install -r requirements.txt

if not exist .env (
    echo Creating .env file...
    copy .env.example .env
    echo IMPORTANT: Edit backend\.env with your API keys and database URL
)

cd ..
echo Backend setup complete!
echo.

echo [3/4] Setting up frontend...
cd frontend
if not exist node_modules (
    echo Installing npm dependencies...
    call npm install
)
cd ..
echo Frontend setup complete!
echo.

echo [4/4] Setup complete!
echo.
echo ========================================
echo Next Steps:
echo ========================================
echo 1. Edit backend\.env with your configuration
echo 2. Create PostgreSQL database: ai_workflow
echo 3. Start backend: cd backend && venv\Scripts\activate && uvicorn app.main:app --reload
echo 4. Start frontend: cd frontend && npm run dev
echo.
echo Backend will run on: http://localhost:8000
echo Frontend will run on: http://localhost:5173
echo API Docs: http://localhost:8000/docs
echo ========================================
pause
