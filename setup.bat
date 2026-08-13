@echo off
setlocal
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 未找到 Python。请安装 Python 3.11 或更高版本并加入 PATH。
  pause
  exit /b 1
)
python -m venv .venv
if errorlevel 1 goto :fail
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :fail
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail
rem 浏览器使用系统自带 Edge，无需下载 Chromium
echo.
echo 安装完成。浏览器使用系统自带 Edge；下一步依次运行 build_input.bat、login.bat、self_test.bat。
pause
exit /b 0

:fail
echo.
echo [ERROR] 安装失败，请查看上方信息。
pause
exit /b 1

