@echo off
setlocal
cd /d "%~dp0"
echo === Gerando o executavel (PyInstaller, modo onedir) ===
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
if not exist ".venv\Scripts\python.exe" ( %PY% -m venv .venv || goto :err )
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip || goto :err
rem Atualiza o yt-dlp antes de empacotar: o YouTube muda com frequencia
pip install -U -r requirements-build.txt || goto :err
powershell -NoProfile -ExecutionPolicy Bypass -File tools\get_deno.ps1 || goto :err
rem python tools\make_icon.py
pyinstaller build.spec --noconfirm --clean || goto :err
echo.
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if defined ISCC (
    "%ISCC%" installer.iss || goto :err
    echo Instalador gerado em installer\
) else (
    echo Inno Setup 6 nao encontrado: pulei o instalador. O programa esta em dist\Shark3\
)
pause
exit /b 0
:err
echo.
echo ERRO no build. Veja as mensagens acima.
pause
exit /b 1
