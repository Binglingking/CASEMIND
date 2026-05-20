#!/usr/bin/env python3
"""CaseMind 一键启动器（Python 版）。

功能：
  - 检查 / 创建 .venv 并安装 backend 依赖（首次）
  - 检查 / 安装 frontend 的 npm 依赖（首次）
  - 强制 UTF-8（PYTHONUTF8=1 + console code page 65001），解决中文乱码
  - 同时启动后端（uvicorn，8888）和前端（vite，5173）
  - 等端口可用后自动打开浏览器
  - Ctrl+C 一次即优雅结束两端

用法：
  python run.py                # 启动
  python run.py --no-browser   # 不自动开浏览器
  python run.py --no-reload    # 后端关掉 --reload
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
IS_WIN = os.name == "nt"
VENV_PY = VENV / ("Scripts" if IS_WIN else "bin") / ("python.exe" if IS_WIN else "python")
DEPS_MARK = VENV / ".deps_ok"
FRONTEND_DIR = ROOT / "frontend"
BACKEND_PORT = 8888
FRONTEND_PORT = 5173


# ------------------------------------------------------------------
# UTF-8 hardening for this launcher process itself
# ------------------------------------------------------------------
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
if IS_WIN:
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass


def tty_color(code: str) -> str:
    return code if sys.stdout.isatty() else ""


C_RESET = tty_color("\033[0m")
C_INFO = tty_color("\033[36m")    # cyan — launcher
C_BACK = tty_color("\033[35m")    # magenta — backend
C_FRONT = tty_color("\033[33m")   # yellow — frontend
C_OK = tty_color("\033[32m")      # green
C_ERR = tty_color("\033[31m")     # red


def log(tag: str, msg: str, color: str = C_INFO) -> None:
    print(f"{color}[{tag}]{C_RESET} {msg}", flush=True)


def die(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    log("error", msg, C_ERR)
    sys.exit(1)


def which_or_die(name: str) -> str:
    p = shutil.which(name)
    if not p:
        die(f"未在 PATH 中找到 `{name}`，请先安装。")
    return p


def ensure_backend() -> None:
    if not VENV_PY.exists():
        log("setup", f"创建虚拟环境 {VENV}")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    if not DEPS_MARK.exists():
        log("setup", "安装 backend/requirements.txt（首次）")
        subprocess.check_call([str(VENV_PY), "-m", "pip", "install", "--upgrade", "pip"])
        subprocess.check_call([
            str(VENV_PY), "-m", "pip", "install",
            "-r", str(ROOT / "backend" / "requirements.txt"),
        ])
        DEPS_MARK.touch()


def ensure_frontend() -> None:
    if not (FRONTEND_DIR / "node_modules").exists():
        npm = which_or_die("npm.cmd" if IS_WIN else "npm")
        log("setup", "执行 npm install（首次，可能需要几分钟）")
        subprocess.check_call([npm, "install"], cwd=str(FRONTEND_DIR))


def port_is_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False


def pids_on_port(port: int) -> list[str]:
    """Find PIDs listening on a TCP port (Windows via netstat, *nix via lsof)."""
    if IS_WIN:
        try:
            out = subprocess.check_output(["netstat", "-ano"], encoding="utf-8", errors="replace")
        except Exception:
            return []
        pids: set[str] = set()
        token = f":{port} "
        for line in out.splitlines():
            if token in line and "LISTENING" in line:
                parts = line.strip().split()
                if parts:
                    pids.add(parts[-1])
        return list(pids)
    try:
        out = subprocess.check_output(["lsof", "-ti", f"tcp:{port}"], encoding="utf-8", errors="replace")
        return [p for p in out.split() if p]
    except Exception:
        return []


def free_port(port: int, label: str) -> None:
    """If a stale process is on `port`, kill it so the new server can bind."""
    if not port_is_listening(port):
        return
    pids = pids_on_port(port)
    if not pids:
        log("warn", f"端口 {port} 已被占用但未定位到进程，请手动排查", C_ERR)
        return
    log("cleanup", f"{label} 端口 {port} 被 PID {', '.join(pids)} 占用，尝试清理", C_INFO)
    
    # 第一轮：温和终止所有相关进程
    for pid in pids:
        try:
            if IS_WIN:
                subprocess.call(["taskkill", "/PID", pid],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.call(["kill", pid],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    
    # 等待 2 秒让进程正常退出
    time.sleep(2)
    
    # 第二轮：检查是否还有进程占用，强制杀死
    if port_is_listening(port):
        remaining_pids = pids_on_port(port)
        if remaining_pids:
            log("info", f"仍有进程占用端口，强制清理 PID {', '.join(remaining_pids)}", C_INFO)
            for pid in remaining_pids:
                try:
                    if IS_WIN:
                        subprocess.call(["taskkill", "/F", "/PID", pid],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        subprocess.call(["kill", "-9", pid],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
    
    # 等 OS 释放端口 - 增加等待时间
    for attempt in range(50):  # 最多等待 10 秒
        if not port_is_listening(port):
            log("ok", f"端口 {port} 已成功释放", C_OK)
            return
        time.sleep(0.2)
    
    log("warn", f"清理后端口 {port} 仍被占用，可能影响启动", C_ERR)
    log("info", f"建议：1. 手动运行 'python stop.py' 2. 或在任务管理器中结束 python.exe 进程", C_INFO)


def wait_port(port: int, name: str, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_is_listening(port):
            return True
        time.sleep(0.4)
    log("warn", f"{name} 端口 {port} 在 {int(timeout)}s 内未监听，请查看各自窗口日志", C_ERR)
    return False


def spawn_backend(reload: bool) -> subprocess.Popen:
    cmd = [
        str(VENV_PY), "-m", "uvicorn", "backend.main:app",
        "--host", "127.0.0.1", "--port", str(BACKEND_PORT),
        "--no-access-log",  # 用 backend.main 里的中间件接管日志
    ]
    if reload:
        cmd.append("--reload")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    log("backend", f"启动：{' '.join(cmd)}", C_BACK)
    # 关键：不捕获 stdout / stderr，子进程直接写到本终端，保持实时日志。
    # Windows 下用 CREATE_NEW_PROCESS_GROUP，以便发 CTRL_BREAK_EVENT 精准停子进程。
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WIN else 0  # type: ignore[attr-defined]
    return subprocess.Popen(cmd, cwd=str(ROOT), env=env, creationflags=creationflags)


def spawn_frontend() -> subprocess.Popen:
    npm = which_or_die("npm.cmd" if IS_WIN else "npm")
    env = os.environ.copy()
    env.setdefault("FORCE_COLOR", "1")
    log("frontend", f"启动：{npm} run dev", C_FRONT)
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WIN else 0  # type: ignore[attr-defined]
    return subprocess.Popen([npm, "run", "dev"], cwd=str(FRONTEND_DIR), env=env,
                            creationflags=creationflags)


def terminate(proc: subprocess.Popen, name: str) -> None:
    if proc.poll() is not None:
        return
    log("stop", f"结束 {name} (pid={proc.pid})", C_INFO)
    try:
        if IS_WIN:
            proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        else:
            proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        log("stop", f"{name} 未在 8s 内退出，强制 kill", C_ERR)
        proc.kill()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="CaseMind 启动器")
    parser.add_argument("--no-browser", action="store_true", help="启动后不打开浏览器")
    parser.add_argument("--no-reload", action="store_true", help="后端关闭 --reload（推荐生产态）")
    parser.add_argument("--backend-only", action="store_true", help="只启动后端")
    parser.add_argument("--frontend-only", action="store_true", help="只启动前端")
    args = parser.parse_args()

    log("info", f"项目根目录：{ROOT}")
    which_or_die("python" if IS_WIN else "python3")
    if not args.backend_only:
        which_or_die("node")
        which_or_die("npm.cmd" if IS_WIN else "npm")

    if not args.frontend_only:
        ensure_backend()
    if not args.backend_only:
        ensure_frontend()

    procs: list[tuple[str, subprocess.Popen]] = []
    try:
        if not args.frontend_only:
            free_port(BACKEND_PORT, "backend")
            procs.append(("backend", spawn_backend(reload=not args.no_reload)))

        if not args.backend_only:
            free_port(FRONTEND_PORT, "frontend")
            procs.append(("frontend", spawn_frontend()))

        # 等端口可用
        if not args.frontend_only:
            wait_port(BACKEND_PORT, "backend", timeout=60)
        if not args.backend_only:
            wait_port(FRONTEND_PORT, "frontend", timeout=60)

        log("ok", f"Backend : http://127.0.0.1:{BACKEND_PORT}", C_OK)
        log("ok", f"Frontend: http://127.0.0.1:{FRONTEND_PORT}", C_OK)
        log("info", "Ctrl+C 一次即可同时停止两端。")

        if not args.no_browser and not args.backend_only:
            try:
                webbrowser.open(f"http://127.0.0.1:{FRONTEND_PORT}")
            except Exception:
                pass

        # 守护：任何一个子进程退出就带走另一个
        while procs:
            for name, p in list(procs):
                rc = p.poll()
                if rc is not None:
                    log("exit", f"{name} 退出（code={rc}），一并结束其他服务", C_ERR)
                    procs.remove((name, p))
                    raise KeyboardInterrupt
            time.sleep(0.5)
        return 0

    except KeyboardInterrupt:
        log("info", "收到中断信号，正在关闭 …")
        return 0
    finally:
        for name, p in procs:
            terminate(p, name)
        log("info", "已退出。")


if __name__ == "__main__":
    sys.exit(main())
