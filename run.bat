@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Ambiente nao encontrado. Execute setup.bat primeiro.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" main.py
