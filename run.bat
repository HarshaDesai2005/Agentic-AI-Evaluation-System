@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found. Create it first:
  echo   py -3.11 -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)

set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if exist "%OLLAMA%" (
  curl -s -o NUL --max-time 2 http://127.0.0.1:11434/api/tags
  if errorlevel 1 (
    echo Starting Ollama...
    start "" "%OLLAMA%" serve
    timeout /t 3 /nobreak >NUL
  )
)

".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
