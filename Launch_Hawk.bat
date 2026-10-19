@echo off
setlocal
cd /d "%~dp0"
if exist "runtime\python.exe" (
  set "TCL_LIBRARY=runtime\tcl\tcl8.6"
  set "TK_LIBRARY=runtime\tcl\tk8.6"
  "runtime\python.exe" -E Hawkes_AI_Companion.py --hawk
  if errorlevel 1 pause
  exit /b
)
if not exist ".venv\Scripts\python.exe" (
  call Setup_Hawkes_AI.bat
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" Hawkes_AI_Companion.py --hawk
if errorlevel 1 pause
