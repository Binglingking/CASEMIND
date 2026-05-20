"""Memory version management — snapshot memory.md on build/save for rollback."""
from __future__ import annotations

import json
from pathlib import Path

from backend.core.project import project_manager
from backend.core.timeutil import utc_iso_z


def _versions_dir(project: str) -> Path:
    d = project_manager.mem_dir(project) / "versions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path(project: str) -> Path:
    return _versions_dir(project) / "versions.json"


def _load_index(project: str) -> dict:
    p = _index_path(project)
    if not p.exists():
        return {"versions": [], "current": None, "next_id": 1}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        # ensure keys
        data.setdefault("versions", [])
        data.setdefault("current", None)
        data.setdefault("next_id", len(data["versions"]) + 1)
        return data
    except Exception:
        return {"versions": [], "current": None, "next_id": 1}


def _save_index(project: str, data: dict) -> None:
    _index_path(project).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def create_version(project: str, source: str, summary: str) -> dict | None:
    mem = project_manager.mem_dir(project) / "memory.md"
    prompt = project_manager.mem_dir(project) / "memory_prompt.txt"
    if not mem.exists():
        return None

    idx = _load_index(project)
    vid = f"v{idx['next_id']:03d}"
    vdir = _versions_dir(project) / vid
    vdir.mkdir(parents=True, exist_ok=True)

    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "memory.md").write_text(mem.read_text(encoding="utf-8"), encoding="utf-8")
    if prompt.exists():
        (vdir / "memory_prompt.txt").write_text(prompt.read_text(encoding="utf-8"), encoding="utf-8")

    entry = {
        "id": vid,
        "created_at": utc_iso_z(),
        "source": source,
        "summary": summary,
    }
    idx["versions"].append(entry)
    idx["current"] = vid
    idx["next_id"] += 1
    _save_index(project, idx)
    return entry


def list_versions(project: str) -> list[dict]:
    return list(reversed(_load_index(project)["versions"]))


def get_version(project: str, version_id: str) -> dict | None:
    vdir = _versions_dir(project) / version_id
    mem_file = vdir / "memory.md"
    if not mem_file.exists():
        return None
    result = {
        "id": version_id,
        "memory_md": mem_file.read_text(encoding="utf-8"),
    }
    prompt_file = vdir / "memory_prompt.txt"
    if prompt_file.exists():
        result["memory_prompt"] = prompt_file.read_text(encoding="utf-8")
    return result


def restore_version(project: str, version_id: str) -> dict:
    data = get_version(project, version_id)
    if data is None:
        raise ValueError(f"版本不存在: {version_id}")
    mem = project_manager.mem_dir(project) / "memory.md"
    mem.write_text(data["memory_md"], encoding="utf-8")
    prompt = project_manager.mem_dir(project) / "memory_prompt.txt"
    if data.get("memory_prompt"):
        prompt.write_text(data["memory_prompt"], encoding="utf-8")
    idx = _load_index(project)
    idx["current"] = version_id
    _save_index(project, idx)
    return {"ok": True, "restored": version_id}