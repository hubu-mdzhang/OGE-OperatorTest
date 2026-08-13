@echo off
setlocal
if not exist .venv\Scripts\python.exe (
  echo [ERROR] 未找到 .venv，请先运行 setup.bat
  pause
  exit /b 1
)
.venv\Scripts\python.exe self_check.py
set "ERR=%ERRORLEVEL%"
pause
exit /b %ERR%

