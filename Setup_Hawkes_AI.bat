@echo off
setlocal
cd /d "%~dp0"
if exist "runtime\python.exe" (
  echo Use Launch_Compact.bat or Launch_Hawk.bat. The portable runtime is ready.
  exit /b 0
)
if not exist ".venv\Scripts\python.exe" (
  py -3 -c "import sys, tkinter; assert sys.version_info >= (3,12)"
  if errorlevel 1 goto missing
  py -3 -m venv .venv
  if errorlevel 1 goto failed
)
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0browser"
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m playwright install chromium --only-shell
if errorlevel 1 goto failed
".venv\Scripts\python.exe" scripts\setup_assets.py
if errorlevel 1 goto failed
echo Setup complete. Start Ollama, then open Launch_Compact.bat or Launch_Hawk.bat.
pause
exit /b 0
:missing
echo Install 64-bit Python 3.12 or newer with Tcl/Tk and pip, then retry.
pause
exit /b 1
:failed
echo Setup failed. Check the error above and your internet connection, then retry.
pause
exit /b 1
