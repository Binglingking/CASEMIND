from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from backend.core import folders as folders_store
from backend.core.file_scanner import scan_folder


def list_folders_with_stats(project: str) -> list[dict]:
    """Summary only — no files array to keep payload light."""
    out = []
    for f in folders_store.list_folders(project):
        p = Path(f)
        files = scan_folder(f) if p.exists() else []
        by_ext = Counter((Path(x.rel_path).suffix.lower() or "(no-ext)") for x in files)
        total_size = sum(x.size for x in files)
        out.append({
            "path": f,
            "exists": p.exists(),
            "file_count": len(files),
            "total_size": total_size,
            "by_ext": dict(by_ext),
        })
    return out


def list_files_of_folder(project: str, path: str) -> dict:
    """Detailed files for ONE configured folder. Validates path is registered."""
    registered = [str(Path(f).resolve()) for f in folders_store.list_folders(project)]
    requested = str(Path(path).resolve())
    if requested not in registered:
        # fallback: compare raw strings too (Windows case / separator quirks)
        raw_registered = folders_store.list_folders(project)
        if path not in raw_registered and requested not in raw_registered:
            raise ValueError(f"Path not registered for project: {path}")

    p = Path(path)
    if not p.exists():
        return {"path": path, "exists": False, "files": []}

    files = scan_folder(path)
    items = []
    for x in files:
        fp = Path(x.path)
        items.append({
            "name": fp.name,
            "rel_path": x.rel_path.replace("\\", "/"),
            "abs_path": x.path,
            "ext": (fp.suffix.lower() or "(no-ext)"),
            "size": int(x.size),
            "mtime": float(x.mtime),
        })
    items.sort(key=lambda r: r["rel_path"].lower())
    return {
        "path": path,
        "exists": True,
        "count": len(items),
        "total_size": sum(i["size"] for i in items),
        "files": items,
    }


def add_folder(project: str, path: str) -> dict:
    p = Path(path).expanduser()
    if not p.exists():
        raise ValueError(f"Path does not exist: {p}")
    if not p.is_dir():
        raise ValueError(f"Path is not a directory: {p}")
    folders = folders_store.add_folder(project, str(p))
    return {"folders": folders}


def remove_folder(project: str, path: str) -> dict:
    folders = folders_store.remove_folder(project, path)
    return {"folders": folders}


def open_file(project: str, path: str) -> dict:
    """Open a local file with the OS default application. Guarded to registered
    project folders so an attacker can't make us open arbitrary system files."""
    target = Path(path).resolve()
    if not target.exists():
        raise ValueError(f"File does not exist: {target}")
    if not target.is_file():
        raise ValueError(f"Not a file: {target}")

    registered = [Path(f).resolve() for f in folders_store.list_folders(project)]
    if not registered:
        raise ValueError("项目尚未配置任何目录，不允许打开任意文件。")
    allowed = False
    for root in registered:
        try:
            target.relative_to(root)
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        raise ValueError(
            "安全拒绝：目标文件不在该项目任何已注册目录之内。"
        )

    try:
        if sys.platform.startswith("win"):
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
    except Exception as e:
        raise RuntimeError(f"打开文件失败：{e}") from e
    return {"ok": True, "path": str(target)}
