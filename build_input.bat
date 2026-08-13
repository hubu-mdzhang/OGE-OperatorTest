@echo off
setlocal
if not exist .venv\Scripts\python.exe (
  echo [ERROR] 未找到 .venv，请先运行 setup.bat
  pause
  exit /b 1
)
set "SOURCE_XLSX=%~1"
if "%SOURCE_XLSX%"=="" set "SOURCE_XLSX=input\source\副本算子排序表0806返修.xlsx"
.venv\Scripts\python.exe tools\build_input.py --excel "%SOURCE_XLSX%" --output input\operators.csv
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" echo [ERROR] CSV 构建或质检失败。
pause
exit /b %ERR%

