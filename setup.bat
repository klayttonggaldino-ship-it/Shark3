@echo off
setlocal
cd /d "%~dp0"
echo === Preparando o ambiente (Python + dependencias + Deno) ===
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv || goto :err
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip || goto :err
pip install -r requirements.txt || goto :err
powershell -NoProfile -ExecutionPolicy Bypass -File tools\get_deno.ps1 || goto :err
echo.
echo Tudo pronto! Para abrir o programa, execute run.bat
pause
exit /b 0
:err
echo.
echo ERRO durante a instalacao. Veja as mensagens acima.
pause
exit /b 1
