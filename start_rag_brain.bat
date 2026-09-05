@echo off
chcp 65001 >nul
cd /d "%~dp0"
netstat -ano | findstr ":19530" >nul 2>&1 || (echo Milvus not listening, start it first. & pause & exit /b 1)
set "PY=python"
if exist "D:\software\Anaconda\envs\python312\python.exe" set "PY=D:\software\Anaconda\envs\python312\python.exe"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
echo http://127.0.0.1:8001
"%PY%" -u -m uvicorn knowledge.front.api.main:app --host 0.0.0.0 --port 8001
pause
