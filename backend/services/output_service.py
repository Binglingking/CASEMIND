"""Output file management for testcase JSON and XMind Markdown files.

Stored under outputs/testcases/<project>/ and outputs/xmind/<project>/.
No JSON index — the filesystem is the source of truth.
"""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path

from backend.core.project import project_manager


SAFE_KINDS = {"testcase", "xmind", "req_analysis"}


def _validate_kind(kind: str) -> None:
    if kind not in SAFE_KINDS:
        raise ValueError(f"kind must be testcase, xmind, or req_analysis, got: {kind}")


def _validate_filename(filename: str) -> str:
    name = Path(filename).name
    if ".." in name or "/" in name or "\\" in name:
        raise ValueError(f"Invalid filename: {filename}")
    return name


def _dir_for(project: str, kind: str) -> Path:
    _validate_kind(kind)
    if kind == "testcase":
        return project_manager.out_testcase_dir(project)
    if kind == "xmind":
        return project_manager.out_xmind_dir(project)
    return project_manager.out_req_analysis_dir(project)


def list_outputs(project: str, kind: str | None = None) -> list[dict]:
    kinds = [kind] if kind else sorted(SAFE_KINDS)
    items = []
    for k in kinds:
        try:
            d = _dir_for(project, k)
        except Exception:
            continue
        if not d.exists():
            continue
        for p in d.iterdir():
            if not p.is_file():
                continue
            if k == "req_analysis" and p.suffix.lower() != ".pdf":
                continue
            try:
                st = p.stat()
            except Exception:
                continue
            items.append({
                "name": p.name,
                "kind": k,
                "size": int(st.st_size),
                "mtime": float(st.st_mtime),
                "path": str(p),
            })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def read_output_content(project: str, kind: str, filename: str) -> dict:
    _validate_kind(kind)
    fname = _validate_filename(filename)
    d = _dir_for(project, kind)
    target = d / fname
    if not target.exists() or not target.is_file():
        raise ValueError(f"文件不存在: {filename}")

    st = target.stat()
    if kind == "req_analysis":
        return {
            "name": fname,
            "kind": kind,
            "size": int(st.st_size),
            "mtime": float(st.st_mtime),
            "content_type": mimetypes.guess_type(fname)[0] or "application/pdf",
            "truncated": False,
        }

    raw = target.read_text(encoding="utf-8")
    truncated = False

    if kind == "testcase":
        max_chars = 40000
        if len(raw) > max_chars:
            truncated = True
        if fname.endswith(".md"):
            from backend.services.md_case_utils import md_to_cases
            return {
                "name": fname,
                "kind": kind,
                "size": int(st.st_size),
                "mtime": float(st.st_mtime),
                "cases": md_to_cases(raw),
                "markdown": raw[:max_chars] if len(raw) > max_chars else raw,
                "truncated": truncated,
            }
        try:
            data = json.loads(raw)
        except Exception:
            data = {"cases": [], "_raw": raw}
        return {
            "name": fname,
            "kind": kind,
            "size": int(st.st_size),
            "mtime": float(st.st_mtime),
            "data": data,
            "cases": data.get("cases", []) if isinstance(data, dict) else [],
            "truncated": truncated,
        }
    else:
        max_chars = 40000
        content = raw
        if len(content) > max_chars:
            content = content[:max_chars]
            truncated = True
        return {
            "name": fname,
            "kind": kind,
            "size": int(st.st_size),
            "mtime": float(st.st_mtime),
            "markdown": content,
            "truncated": truncated,
        }


def read_output_raw(project: str, kind: str, filename: str) -> str:
    _validate_kind(kind)
    fname = _validate_filename(filename)
    d = _dir_for(project, kind)
    target = d / fname
    if not target.exists() or not target.is_file():
        raise ValueError(f"文件不存在: {filename}")
    return target.read_text(encoding="utf-8")


def output_path(project: str, kind: str, filename: str) -> Path:
    _validate_kind(kind)
    fname = _validate_filename(filename)
    target = _dir_for(project, kind) / fname
    if not target.exists() or not target.is_file():
        raise ValueError(f"File does not exist: {filename}")
    return target


def rename_output(project: str, kind: str, old_name: str, new_name: str) -> dict:
    _validate_kind(kind)
    old = _validate_filename(old_name)
    new = _validate_filename(new_name)
    if not new.strip():
        raise ValueError("新文件名不能为空")
    d = _dir_for(project, kind)
    src = d / old
    if not src.exists():
        raise ValueError(f"文件不存在: {old_name}")
    dst = d / new
    if dst.exists():
        raise ValueError(f"目标文件已存在: {new_name}")
    src.rename(dst)
    return {"ok": True, "old_name": old, "new_name": new}


def delete_output(project: str, kind: str, filename: str) -> dict:
    _validate_kind(kind)
    fname = _validate_filename(filename)
    d = _dir_for(project, kind)
    target = d / fname
    if not target.exists():
        raise ValueError(f"文件不存在: {filename}")
    target.unlink()
    return {"ok": True, "name": fname}
