@echo off
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Could not find venv\Scripts\python.exe.
    echo Create the virtual environment and install dependencies first:
    echo python -m venv venv
    echo venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

venv\Scripts\python.exe desktop.py

if errorlevel 1 (
    echo.
    echo The desktop app closed with an error.
    pause
)
