"""Project isolation and lifecycle management."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime
from pathlib import Path

from backend.config import settings
from backend.core.timeutil import utc_iso_z


PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9_\-一-龥]{1,64}$")


def sanitize_name(name: str) -> str:
    name = (name or "").strip()
    if not PROJECT_NAME_RE.match(name):
        raise ValueError("Invalid project name (allowed: letters, digits, _, -, Chinese; max 64 chars).")
    return name


def _hash_password(password: str) -> str:
    """PBKDF2-SHA256 with random salt."""
    salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000,
    ).hex()
    return f"{salt}:{pw_hash}"


def _verify_password(stored: str, password: str) -> bool:
    """Verify password against stored hash."""
    try:
        salt, pw_hash = stored.split(":", 1)
    except ValueError:
        return False
    computed = hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000,
    ).hex()
    return computed == pw_hash


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
        return [self.get_meta(n) for n in sorted(names)]

    def create(self, name: str) -> dict:
        name = sanitize_name(name)
        (self.root_docs / name).mkdir(parents=True, exist_ok=True)
        (self.root_mem / name).mkdir(parents=True, exist_ok=True)
        (self.root_out / "xmind" / name).mkdir(parents=True, exist_ok=True)
        (self.root_out / "testcases" / name).mkdir(parents=True, exist_ok=True)
        (self.root_out / "req_analysis" / name).mkdir(parents=True, exist_ok=True)
        meta = {"name": name, "created_at": utc_iso_z(), "owner": "", "has_password": False}
        (self.root_mem / name / "project.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return self.get_meta(name)

    def get_meta(self, name: str) -> dict:
        """Get project metadata without password hash."""
        name = sanitize_name(name)
        meta_path = self.root_mem / name / "project.json"
        if not meta_path.exists():
            return {"name": name, "created_at": "", "has_password": False, "owner": ""}
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {"name": name, "created_at": "", "has_password": False, "owner": ""}
        return {
            "name": raw.get("name", name),
            "created_at": raw.get("created_at", ""),
            "has_password": bool(raw.get("password_hash", "")),
            "owner": raw.get("owner", ""),
        }

    def set_password(self, name: str, owner: str, password: str) -> dict:
        """Set owner and password for a project. Returns updated meta."""
        name = sanitize_name(name)
        if not owner.strip():
            raise ValueError("所有者姓名不能为空")
        if len(password) < 4:
            raise ValueError("密码至少需要4个字符")
        meta_path = self.root_mem / name / "project.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {"name": name, "created_at": utc_iso_z()}
        else:
            meta = {"name": name, "created_at": utc_iso_z()}
        meta["owner"] = owner.strip()
        meta["password_hash"] = _hash_password(password)
        meta["has_password"] = True
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.get_meta(name)

    def verify_password(self, name: str, password: str) -> bool:
        """Verify project password. Returns True if no password set or project doesn't exist."""
        name = sanitize_name(name)
        meta_path = self.root_mem / name / "project.json"
        if not meta_path.exists():
            return True
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return True
        stored = raw.get("password_hash", "")
        if not stored:
            return True
        return _verify_password(stored, password)

    def change_password(self, name: str, old_password: str, new_password: str) -> dict:
        """Change project password (requires old password verification)."""
        name = sanitize_name(name)
        if len(new_password) < 4:
            raise ValueError("新密码至少需要4个字符")
        if not self.verify_password(name, old_password):
            raise ValueError("原密码错误")
        meta_path = self.root_mem / name / "project.json"
        if not meta_path.exists():
            raise ValueError("项目不存在")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["password_hash"] = _hash_password(new_password)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.get_meta(name)

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

    def out_req_analysis_dir(self, name: str) -> Path:
        d = self.root_out / "req_analysis" / sanitize_name(name)
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
            self.root_out / "req_analysis" / name,
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
