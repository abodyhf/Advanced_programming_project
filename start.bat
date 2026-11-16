@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto error
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto error
echo.
echo Open http://127.0.0.1:8000 in your browser. Keep this window open.
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto error
exit /b 0
:error
echo.
echo Could not start. Check that Python 3.11 or newer is installed and internet is available for the first setup.
pause
exit /b 1
