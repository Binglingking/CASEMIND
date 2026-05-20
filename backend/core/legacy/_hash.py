"""Legacy 资产文件级内容哈希。

file_id 统一用 sha1(file_bytes)[:8]，保证：
  - 重传完全相同字节 → 同 file_id → upsert 幂等
  - case_id / node_id 拼接此 file_id → 内容相同则 ID 稳定，可比较
"""
from __future__ import annotations

import hashlib
from pathlib import Path


_CHUNK = 65536


def file_content_id(path: Path) -> str:
    """sha1(file_bytes)[:8]。

    流式读取，避免大文件全量入内存。
    """
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()[:8]


def bytes_content_id(data: bytes) -> str:
    """同 file_content_id 但接受字节，便于 ingest 时复用。"""
    return hashlib.sha1(data).hexdigest()[:8]
