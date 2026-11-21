@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 py -3 -m venv .venv
  if errorlevel 1 goto error
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto error

rem An earlier copy of this app may still be running on port 8000 with old code or an old
rem catalogue. Stop that copy (only a Python process that is running app.py) so this one can start.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $_.OwningProcess); if ($p.Name -like 'python*' -and $p.CommandLine -like '*app.py*') { Write-Host 'Stopping the earlier WatchTogether copy...'; Stop-Process -Id $p.ProcessId -Force; Start-Sleep 2 } else { Write-Host ('Port 8000 is used by another program: ' + $p.Name) } }"

echo.
echo Open http://127.0.0.1:8000 in your browser. Keep this window open.
start "" /min cmd /c "timeout /t 6 /nobreak >nul & start http://127.0.0.1:8000"
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto error
exit /b 0
:error
echo.
echo Could not start. Check that Python 3.11 or newer is installed, that internet is available for the
echo first setup, and that no other program is using port 8000.
pause
exit /b 1
