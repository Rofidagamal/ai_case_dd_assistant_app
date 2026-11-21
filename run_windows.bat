@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
rem Skip Streamlit's one-time "enter your email" question
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  mkdir "%USERPROFILE%\.streamlit" 2>nul
  (echo [general]& echo email = "") > "%USERPROFILE%\.streamlit\credentials.toml"
)
streamlit run app.py --server.headless false
pause
