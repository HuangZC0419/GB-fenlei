@echo off
setlocal
cd /d "%~dp0"

echo.
echo ============================================
echo   Aviation Standard Classifier - Win7
echo ============================================
echo.

if not exist "frontend\dist\index.html" (
    echo [ERROR] frontend\dist\index.html not found.
    echo         Build the frontend on a machine with Node.js 18+:
    echo             cd frontend
    echo             npm ci
    echo             npm run build
    echo.
    pause
    exit /b 1
)

set "CONDA_CMD=call conda"
where conda >nul 2>nul
if not errorlevel 1 goto conda_ready
if exist "F:\anaconda2024.06\condabin\conda.bat" (
    set "CONDA_CMD=call F:\anaconda2024.06\condabin\conda.bat"
    goto conda_ready
)
echo [ERROR] conda was not found. Install Anaconda/Miniconda or add conda to PATH.
pause
exit /b 1

:conda_ready
echo [1/3] Checking Python and backend dependencies...
%CONDA_CMD% activate CF >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Cannot activate conda environment CF.
    pause
    exit /b 1
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python 3.8+ is required. Current version:
    python -V
    pause
    exit /b 1
)
python -c "import fastapi, uvicorn, openpyxl, multipart" >nul 2>nul
if not errorlevel 1 goto backend_ready
echo       Installing backend requirements...
python -m pip install -r backend\requirements.txt
if errorlevel 1 (
    echo [ERROR] Backend dependency installation failed.
    pause
    exit /b 1
)

:backend_ready
echo [2/3] Starting backend on http://127.0.0.1:8000 ...
start "AviationStandard-Win7" /D "%~dp0backend" cmd /k "%CONDA_CMD% activate CF && python -m uvicorn main:app --host 127.0.0.1 --port 8000"

echo [3/3] Waiting for backend...
set "READY="
for /l %%i in (1,1,60) do (
    if not defined READY (
        python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=1).getcode() == 200 else 1)" >nul 2>nul
        if errorlevel 1 (
            ping -n 2 127.0.0.1 >nul
        ) else (
            set "READY=1"
        )
    )
)
if not defined READY (
    echo [ERROR] Backend did not become ready within 60 seconds.
    echo         Check the backend window for the error message.
    pause
    exit /b 1
)

start "" "http://127.0.0.1:8000"
echo.
echo Started. Browser: http://127.0.0.1:8000
echo Close the backend window to stop the service.
pause >nul
