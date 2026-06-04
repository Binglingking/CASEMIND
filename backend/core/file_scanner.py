"""Recursive local folder scanner for supported docs."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from backend.core.parser import SUPPORTED_EXTS


@dataclass
class ScannedFile:
    path: str       # absolute
    rel_path: str   # path relative to its root
    root: str
    size: int
    mtime: float

    def key(self) -> str:
        return self.path


def scan_folder(root: str) -> list[ScannedFile]:
    out: list[ScannedFile] = []
    p = Path(root)
    if not p.exists() or not p.is_dir():
        return out
    for f in p.rglob("*"):
        if not f.is_file():
            continue
        # 跳过 Office 临时文件（如 ~$xxx.docx）
        if f.name.startswith("~$"):
            continue
        if f.suffix.lower() not in SUPPORTED_EXTS:
            continue
        try:
            st = f.stat()
        except OSError:
            continue
        out.append(ScannedFile(
            path=str(f.resolve()),
            rel_path=str(f.relative_to(p)),
            root=str(p.resolve()),
            size=st.st_size,
            mtime=st.st_mtime,
        ))
    return out


def scan_many(roots: Iterable[str]) -> list[ScannedFile]:
    seen: dict[str, ScannedFile] = {}
    for r in roots:
        for f in scan_folder(r):
            seen[f.path] = f   # later root wins; paths are absolute so usually unique
    return list(seen.values())


def hash_file(path: str, chunk: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        while True:
            b = fp.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()
