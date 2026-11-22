@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    echo [WARN] .venv not found. Falling back to the system interpreter.
    echo        Run scripts\setup_windows.bat first for a reproducible install.
    set "PYTHON=python"
)

"%PYTHON%" main.py
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo J.A.V.E.D. exited with code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
