@echo off
rem ============================================================
rem  JADELY - double-click launcher.
rem  Opens the hub window (launcher, store, news, notes).
rem  For a single app:  python app.py --app store
rem ============================================================
setlocal
cd /d "%~dp0"

rem Prefer pythonw so no console window appears; fall back to python.
for %%I in (pythonw.exe) do set "PYW=%%~$PATH:I"
if defined PYW (
    start "" "%PYW%" "%~dp0app.py" %*
    exit /b 0
)

for %%I in (python.exe) do set "PY=%%~$PATH:I"
if defined PY (
    "%PY%" "%~dp0app.py" %*
    exit /b %errorlevel%
)

echo Python was not found on PATH.
echo Install Python 3.10+ from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
pause
exit /b 1
