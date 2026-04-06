@echo off
echo 停止所有Python进程...
taskkill /f /im python.exe 2>nul
taskkill /f /im python3.12.exe 2>nul
timeout /t 2 /nobreak >nul

echo 启动GeoAI后端服务...
.\venv\Scripts\python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000