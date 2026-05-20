"""时间工具：统一产出 naive-UTC ISO + "Z" 字符串的现代替代品。

`datetime.utcnow()` 在 Python 3.12 起 deprecation，历史代码写的是
`datetime.utcnow().isoformat() + "Z"`，直接切到 `datetime.now(timezone.utc)`
会让 isoformat 带上 `+00:00` 后缀，与既有产物不兼容；这里用 strftime 保持
字面格式（微秒精度 + "Z"）。
"""
from __future__ import annotations

from datetime import datetime, timezone


def utc_iso_z() -> str:
    """返回 "YYYY-MM-DDTHH:MM:SS.ffffffZ" 格式的 UTC 时间串。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def utc_now() -> datetime:
    """返回 tz-aware UTC datetime（用于需要 datetime 对象的地方）。"""
    return datetime.now(timezone.utc)


def utc_compact() -> str:
    """返回 "YYYYMMDD-HHMMSS" 紧凑时间串，用于文件名。"""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
