"""Per-project file index — drives incremental diff."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from backend.core.project import project_manager


@dataclass
class IndexEntry:
    path: str
    size: int
    mtime: float
    hash: str
    ingested_at: str
    summary_path: str = ""   # relative to mem_dir


@dataclass
class FileIndex:
    files: dict[str, IndexEntry] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"files": {k: asdict(v) for k, v in self.files.items()}}

    @classmethod
    def from_json(cls, data: dict) -> "FileIndex":
        out = cls()
        for k, v in (data.get("files") or {}).items():
            try:
                out.files[k] = IndexEntry(**v)
            except Exception:
                continue
        return out


def index_path(project: str) -> Path:
    return project_manager.mem_dir(project) / "file_index.json"


def load_index(project: str) -> FileIndex:
    p = index_path(project)
    if not p.exists():
        return FileIndex()
    try:
        return FileIndex.from_json(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return FileIndex()


def save_index(project: str, idx: FileIndex):
    p = index_path(project)
    p.write_text(json.dumps(idx.to_json(), ensure_ascii=False, indent=2),
                 encoding="utf-8")
