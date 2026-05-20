#!/usr/bin/env python3
"""CaseMind 停止脚本：按端口杀掉后端(8888) 和 前端(5173) 进程。"""
from __future__ import annotations

import os
import subprocess
import sys
import time


PORTS = [8888, 5173]
IS_WIN = os.name == "nt"


def pids_on_port_windows(port: int) -> list[str]:
    try:
        out = subprocess.check_output(["netstat", "-ano"], encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"[error] netstat 调用失败：{e}")
        return []
    pids: set[str] = set()
    token = f":{port} "
    for line in out.splitlines():
        if token in line and "LISTENING" in line:
            parts = line.strip().split()
            if parts:
                pids.add(parts[-1])
    return list(pids)


def kill_process_tree_windows(pid: str) -> None:
    """Kill a process and all its children (important for uvicorn --reload)."""
    # 先尝试获取并杀死子进程
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             f"Get-CimInstance Win32_Process | Where-Object {{$_.ParentProcessId -eq {pid}}} | Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=3
        )
        if result.stdout.strip():
            child_pids = [p.strip() for p in result.stdout.split() if p.strip().isdigit()]
            for child_pid in child_pids:
                print(f"[stop] 杀子进程 PID={child_pid}")
                subprocess.call(["taskkill", "/F", "/PID", child_pid],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    
    # 再杀父进程
    print(f"[stop] 杀进程 PID={pid}")
    subprocess.call(["taskkill", "/F", "/PID", pid],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kill_windows(port: int) -> None:
    pids = pids_on_port_windows(port)
    if not pids:
        print(f"[info] 端口 {port} 未被占用")
        return
    
    for pid in pids:
        kill_process_tree_windows(pid)
    
    # 等待端口释放
    for _ in range(20):
        remaining = pids_on_port_windows(port)
        if not remaining:
            break
        time.sleep(0.2)
    
    if pids_on_port_windows(port):
        print(f"[warn] 端口 {port} 清理后仍被占用")


def kill_unix(port: int) -> None:
    subprocess.call(f"lsof -ti tcp:{port} | xargs -r kill -9", shell=True)


def main() -> int:
    for p in PORTS:
        if IS_WIN:
            kill_windows(p)
        else:
            kill_unix(p)
    print("[ok] 已尝试清理端口", ", ".join(str(p) for p in PORTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
