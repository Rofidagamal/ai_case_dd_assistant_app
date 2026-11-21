@echo off
REM Double-click this ONCE to prepare the app (creates a private Python
REM environment in this folder and installs what the app needs).
cd /d "%~dp0"
py -m venv .venv
call .venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Setup finished. Now double-click run_windows.bat to start the app.
pause
