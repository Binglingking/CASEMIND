@echo off
rem CaseMind 启动脚本：薄壳，转发到 run.py
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 run.py %*
  goto :eof
)
where python >nul 2>&1
if %ERRORLEVEL%==0 (
  python run.py %*
  goto :eof
)
echo [error] 未找到 Python，请先安装 Python 3.11+ 并加入 PATH。
pause
exit /b 1
