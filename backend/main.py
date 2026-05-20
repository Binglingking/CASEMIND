from __future__ import annotations

import logging
import os
import sys
import time
from urllib.parse import unquote

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.config import settings


# ---- UTF-8 hardening --------------------------------------------------------
# Windows 控制台默认是 cp936，日志里含中文路径 / emoji 会变成 ? 或方框。
# 这里把 stdout / stderr 显式 reconfigure 到 utf-8，并把 console code page 切到 65001。
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass


# ---- 自定义 http 日志 -------------------------------------------------------
# uvicorn 默认 access log 输出的是 percent-encoded URL（中文路径变 %E4%B8%AD...），
# 这里接管一下：unquote 还原成中文，并带上耗时和状态码。
_http_log = logging.getLogger("casemind.http")
if not _http_log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s [http] %(message)s", "%H:%M:%S"))
    _http_log.addHandler(_h)
    _http_log.setLevel(logging.INFO)
    _http_log.propagate = False


app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def readable_request_log(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception:
        elapsed = (time.perf_counter() - started) * 1000
        path = unquote(request.url.path)
        query = unquote(request.url.query)
        full = path + (f"?{query}" if query else "")
        _http_log.exception("%s %s -> 500 (%.1fms)", request.method, full, elapsed)
        raise
    elapsed = (time.perf_counter() - started) * 1000
    path = unquote(request.url.path)
    query = unquote(request.url.query)
    full = path + (f"?{query}" if query else "")
    level = logging.INFO if status < 400 else logging.WARNING
    _http_log.log(level, "%s %s -> %d (%.1fms)", request.method, full, status, elapsed)
    return response


app.include_router(router, prefix="/api")


@app.get("/")
def root():
    return {"app": settings.app_name, "ok": True, "api": "/api"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0", port=8888, reload=True,
        access_log=False,  # 关闭 uvicorn 的默认 access log，用上面的中间件替代
    )
