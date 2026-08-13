@echo off
setlocal
if not exist .venv\Scripts\python.exe (
  echo [ERROR] 未找到 .venv，请先运行 setup.bat
  pause
  exit /b 1
)
if not exist input\operators.csv (
  echo [ERROR] 未找到 input\operators.csv，请先运行 build_input.bat
  pause
  exit /b 1
)
.venv\Scripts\python.exe main.py --input input\operators.csv %*
set "ERR=%ERRORLEVEL%"
pause
exit /b %ERR%

