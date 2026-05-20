# CaseMind 启动脚本：薄壳，转发到 run.py
# 用法：powershell -ExecutionPolicy Bypass -File .\start.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

$py = (Get-Command py -ErrorAction SilentlyContinue)
if ($py) {
  & py -3 run.py @args
  exit $LASTEXITCODE
}

$python = (Get-Command python -ErrorAction SilentlyContinue)
if ($python) {
  & python run.py @args
  exit $LASTEXITCODE
}

Write-Error "未找到 Python，请先安装 Python 3.11+ 并加入 PATH。"
exit 1
