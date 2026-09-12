@echo off
setlocal
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto run_py
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto run_python
echo Python 3.10 or later is required. Install Python with the launcher or add it to PATH. 1>&2
set "SH10RT_EXIT=2"
goto finished

:run_py
py -3 "%~dp0scripts\launch_sh10rt.py" %*
set "SH10RT_EXIT=%ERRORLEVEL%"
goto finished

:run_python
python "%~dp0scripts\launch_sh10rt.py" %*
set "SH10RT_EXIT=%ERRORLEVEL%"

:finished
if "%~1"=="" pause
exit /b %SH10RT_EXIT%
