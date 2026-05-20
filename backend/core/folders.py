"""Per-project list of local folders the user has registered."""
from __future__ import annotations

import json
from pathlib import Path

from backend.core.project import project_manager


def _file(project: str) -> Path:
    return project_manager.mem_dir(project) / "folders.json"


def list_folders(project: str) -> list[str]:
    p = _file(project)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return [str(x) for x in (data.get("folders") or [])]
    except Exception:
        return []


def save_folders(project: str, folders: list[str]):
    p = _file(project)
    p.write_text(
        json.dumps({"folders": sorted(set(folders))},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_folder(project: str, path: str) -> list[str]:
    path = str(Path(path).resolve())
    folders = list_folders(project)
    if path not in folders:
        folders.append(path)
    save_folders(project, folders)
    return sorted(set(folders))


def remove_folder(project: str, path: str) -> list[str]:
    path_norm = str(Path(path).resolve())
    current = list_folders(project)
    folders = [f for f in current if str(Path(f).resolve()) != path_norm]
    save_folders(project, folders)
    return folders
