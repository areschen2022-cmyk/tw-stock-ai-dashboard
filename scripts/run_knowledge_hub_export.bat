@echo off
setlocal

set "ROOT=%~dp0.."
set "PY=C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe"
set "HUB_FILE=C:\Users\User\trading_knowledge_hub\data\knowledge.jsonl"

if not exist "%PY%" set "PY=python"

cd /d "%ROOT%" || exit /b 1

git pull --ff-only origin main
if errorlevel 1 (
  echo Warning: git pull failed; continuing with local dashboard data.
)

"%PY%" scripts\export_learning_to_knowledge_hub.py --output "%HUB_FILE%"
exit /b %ERRORLEVEL%
