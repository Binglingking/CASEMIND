#!/usr/bin/env bash
# CaseMind 启动脚本：薄壳，转发到 run.py
set -e
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  exec python3 run.py "$@"
elif command -v python >/dev/null 2>&1; then
  exec python run.py "$@"
else
  echo "[error] 未找到 Python，请先安装 Python 3.11+"
  exit 1
fi
