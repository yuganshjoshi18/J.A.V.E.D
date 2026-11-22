@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo ============================================================
echo  J.A.V.E.D. - Windows setup (Phase 1)
echo ============================================================
echo.

set "PYTHON_CMD="
for %%V in (3.14 3.13 3.12 3.11) do (
    if not defined PYTHON_CMD (
        py -%%V --version >nul 2>&1
        if not errorlevel 1 (
            set "PYTHON_CMD=py -%%V"
        )
    )
)
if not defined PYTHON_CMD (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo [ERROR] Python 3.11-3.14 was not found.
    echo         Install it from https://www.python.org/downloads/windows/
    goto :fail
)

echo Using interpreter: %PYTHON_CMD%
%PYTHON_CMD% -c "import sys; print(sys.version)"
%PYTHON_CMD% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) and sys.version_info < (3,15) else 1)"
if errorlevel 1 (
    echo [ERROR] Python must be 3.11 or newer and below 3.15.
    goto :fail
)

if exist ".venv\Scripts\python.exe" (
    echo Reusing existing virtual environment.
) else (
    echo Creating .venv ...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto :fail
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 goto :fail

echo Upgrading pip ...
python -m pip install --upgrade pip
if errorlevel 1 goto :fail

echo Installing dependencies ...
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo Verifying environment ...
python scripts\check_environment.py
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo  Setup complete.
echo  Start the application with: scripts\run_javed.bat
echo  Configure a Gemini key inside Settings (stored with DPAPI).
echo ============================================================
pause
exit /b 0

:fail
echo.
echo [ERROR] Setup did not complete. Review the messages above.
pause
exit /b 1
