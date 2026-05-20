"""Build log persistence — record each build with summary + detailed log."""
from __future__ import annotations

import json
from pathlib import Path

from backend.core.project import project_manager
from backend.core.timeutil import utc_iso_z


def _builds_dir(project: str) -> Path:
    d = project_manager.mem_dir(project) / "builds"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path(project: str) -> Path:
    return _builds_dir(project) / "builds.json"


def _load_index(project: str) -> dict:
    p = _index_path(project)
    if not p.exists():
        return {"builds": [], "next_id": 1}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        data.setdefault("builds", [])
        data.setdefault("next_id", max([b.get("id", 0) for b in data["builds"]], default=0) + 1)
        return data
    except Exception:
        return {"builds": [], "next_id": 1}


def _save_index(project: str, data: dict) -> None:
    _index_path(project).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def create_build_log(project: str, build_type: str = "incremental") -> int:
    idx = _load_index(project)
    bid = idx["next_id"]
    entry = {
        "id": bid,
        "started_at": utc_iso_z(),
        "finished_at": None,
        "status": "running",
        "summary": "",
        "type": build_type,
        "version_id": None,
    }
    idx["builds"].append(entry)
    idx["next_id"] += 1
    _save_index(project, idx)

    log_file = _builds_dir(project) / f"build_{bid}.json"
    log_file.write_text(json.dumps({"log": []}, ensure_ascii=False), encoding="utf-8")
    return bid


def append_log(project: str, build_id: int, line: str) -> None:
    log_file = _builds_dir(project) / f"build_{build_id}.json"
    if log_file.exists():
        data = json.loads(log_file.read_text(encoding="utf-8"))
        data["log"].append(line)
        log_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_log_lines(project: str, build_id: int, lines: list[str]) -> None:
    for line in lines:
        append_log(project, build_id, line)


def complete_build(project: str, build_id: int, summary: str, status: str = "completed") -> None:
    idx = _load_index(project)
    for b in idx["builds"]:
        if b["id"] == build_id:
            b["finished_at"] = utc_iso_z()
            b["status"] = status
            b["summary"] = summary
            break
    _save_index(project, idx)


def list_builds(project: str) -> list[dict]:
    return list(reversed(_load_index(project)["builds"]))


def get_build(project: str, build_id: int) -> dict | None:
    log_file = _builds_dir(project) / f"build_{build_id}.json"
    if not log_file.exists():
        return None
    return json.loads(log_file.read_text(encoding="utf-8"))


def set_build_version(project: str, build_id: int, version_id: str) -> None:
    idx = _load_index(project)
    for b in idx["builds"]:
        if b["id"] == build_id:
            b["version_id"] = version_id
            break
    _save_index(project, idx)


def get_build_entry(project: str, build_id: int) -> dict | None:
    idx = _load_index(project)
    for b in idx["builds"]:
        if b["id"] == build_id:
            return dict(b)
    return None