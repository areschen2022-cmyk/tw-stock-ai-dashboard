@echo off
setlocal

set "ROOT=%~dp0.."
set "PY=C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

cd /d "%ROOT%" || exit /b 1
"%PY%" scripts\post_optimization_finalize.py %*
exit /b %ERRORLEVEL%
