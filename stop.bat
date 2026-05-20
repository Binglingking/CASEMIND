@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 stop.py %*
  goto :eof
)
where python >nul 2>&1
if %ERRORLEVEL%==0 (
  python stop.py %*
  goto :eof
)
echo [error] 未找到 Python。
exit /b 1
