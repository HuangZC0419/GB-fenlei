@echo off
setlocal
cd /d "%~dp0"

echo.
echo ============================================
echo   Aviation Standard Classifier - Start
echo ============================================
echo.
echo   Backend:  http://127.0.0.1:8000
echo   Frontend: http://127.0.0.1:5173
echo.
echo   Two windows will open. Close them to stop.
echo.

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
echo [1/3] Checking backend dependencies...
%CONDA_CMD% activate CF >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Cannot activate conda environment CF.
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
echo [2/3] Starting backend on port 8000...
start "AviationStandard-Backend" /D "%~dp0backend" cmd /k "%CONDA_CMD% activate CF && python -m uvicorn main:app --host 127.0.0.1 --port 8000"

echo [3/3] Starting frontend on port 5173...
if exist "frontend\node_modules\" goto frontend_ready
echo       First run: installing frontend dependencies...
start "AviationStandard-Frontend" /D "%~dp0frontend" cmd /k "npm install && npm run dev -- --host 127.0.0.1"
goto wait_and_open

:frontend_ready
start "AviationStandard-Frontend" /D "%~dp0frontend" cmd /k "npm run dev -- --host 127.0.0.1"

:wait_and_open
echo.
echo Waiting for services...
powershell -NoProfile -Command "for($i=0;$i -lt 120;$i++){ try { $b=Invoke-WebRequest 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 1; $f=Invoke-WebRequest 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 1; if($b.StatusCode -eq 200 -and $f.StatusCode -eq 200){ exit 0 } } catch {}; Start-Sleep -Seconds 1 }"
start "" "http://127.0.0.1:5173"

echo.
echo Started. If the browser did not open, visit http://127.0.0.1:5173
echo Close the two service windows to stop the program.
echo.
pause >nul
