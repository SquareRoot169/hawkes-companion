@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=.venv\Scripts\python.exe"
if exist "runtime\python.exe" (
  set "PYTHON=runtime\python.exe"
  set "TCL_LIBRARY=runtime\tcl\tcl8.6"
  set "TK_LIBRARY=runtime\tcl\tk8.6"
)
if not exist "%PYTHON%" (
  echo Run Setup_Hawkes_AI.bat first.
  pause
  exit /b 1
)
"%PYTHON%" -m unittest test_rendering test_layout test_v04 test_v05 test_window_switch test_spaced_math test_v06 test_v07 test_pdf_controls test_factorial_math test_tex_export -v
pause
