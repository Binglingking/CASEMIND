"""Project isolation and lifecycle management."""
from __future__ import annotations

import json
import re
from pathlib import Path

from backend.config import settings
from backend.core.timeutil import utc_iso_z


PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9_\-一-龥]{1,64}$")


def sanitize_name(name: str) -> str:
    name = (name or "").strip()
    if not PROJECT_NAME_RE.match(name):
        raise ValueError("Invalid project name (allowed: letters, digits, _, -, Chinese; max 64 chars).")
    return name


class ProjectManager:
    """Directory-layout based project management."""

    def __init__(self):
        self.root_docs = settings.docs_dir
        self.root_mem = settings.memory_dir
        self.root_vec = settings.vector_dir
        self.root_out = settings.outputs_dir

    def list_projects(self) -> list[dict]:
        names: set[str] = set()
        for d in self.root_docs.glob("*"):
            if d.is_dir():
                names.add(d.name)
        for d in self.root_mem.glob("*"):
            if d.is_dir():
                names.add(d.name)
        result = []
        for n in sorted(names):
            meta = self.root_mem / n / "project.json"
            if meta.exists():
                try:
                    result.append(json.loads(meta.read_text(encoding="utf-8")))
                    continue
                except Exception:
                    pass
            result.append({"name": n, "created_at": ""})
        return result

    def create(self, name: str) -> dict:
        name = sanitize_name(name)
        (self.root_docs / name).mkdir(parents=True, exist_ok=True)
        (self.root_mem / name).mkdir(parents=True, exist_ok=True)
        (self.root_out / "xmind" / name).mkdir(parents=True, exist_ok=True)
        (self.root_out / "testcases" / name).mkdir(parents=True, exist_ok=True)
        meta = {"name": name, "created_at": utc_iso_z()}
        (self.root_mem / name / "project.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return meta

    def docs_dir(self, name: str) -> Path:
        name = sanitize_name(name)
        d = self.root_docs / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def mem_dir(self, name: str) -> Path:
        name = sanitize_name(name)
        d = self.root_mem / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def out_testcase_dir(self, name: str) -> Path:
        d = self.root_out / "testcases" / sanitize_name(name)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def out_xmind_dir(self, name: str) -> Path:
        d = self.root_out / "xmind" / sanitize_name(name)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def list_docs(self, name: str) -> list[dict]:
        out = []
        for p in sorted(self.docs_dir(name).glob("*")):
            if p.is_file():
                out.append({
                    "name": p.name,
                    "size": p.stat().st_size,
                    "mtime": datetime.utcfromtimestamp(p.stat().st_mtime).isoformat() + "Z",
                })
        return out

    def delete(self, name: str) -> dict:
        import shutil
        name = sanitize_name(name)
        meta = self.root_mem / name / "project.json"
        if not meta.exists():
            raise ValueError(f"不允许删除自动发现的项目：{name}（仅可删除手动创建的项目）")
        dirs_to_remove = [
            self.root_docs / name,
            self.root_mem / name,
            self.root_out / "testcases" / name,
            self.root_out / "xmind" / name,
        ]
        for d in dirs_to_remove:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
        for pat in [f"{name}.chunks.*", f"{name}.kps.*"]:
            for f in self.root_vec.glob(pat):
                try:
                    f.unlink()
                except Exception:
                    pass
        return {"ok": True, "name": name}


project_manager = ProjectManager()
