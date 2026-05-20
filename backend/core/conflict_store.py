"""冲突记录（ConflictPair）持久化。

文件布局：

    memory/<project>/
    ├── conflicts.json           # ConflictPair[]
    └── conflicts.seq.json       # {"seq": <int>}

职责：纯 IO + 序号生成，不调用 LLM、不包含检测逻辑（见 agents/conflict_detector.py）。
写入一律原子：先写 .tmp 再 rename，避免半写坏文件。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from pydantic import TypeAdapter, ValidationError

from backend.core.project import project_manager
from backend.schemas.conflict import ConflictPair


CONFLICTS_FILE = "conflicts.json"
SEQ_FILE = "conflicts.seq.json"


# ---- paths -----------------------------------------------------------------

def _path(project: str) -> Path:
    return project_manager.mem_dir(project) / CONFLICTS_FILE


def _seq_path(project: str) -> Path:
    return project_manager.mem_dir(project) / SEQ_FILE


# ---- sequence --------------------------------------------------------------

def _load_seq(project: str) -> int:
    p = _seq_path(project)
    if not p.exists():
        return 0
    try:
        return int(json.loads(p.read_text(encoding="utf-8")).get("seq", 0))
    except Exception:
        return 0


def _save_seq(project: str, n: int) -> None:
    _seq_path(project).write_text(
        json.dumps({"seq": n}, ensure_ascii=False), encoding="utf-8",
    )


def next_conflict_id(project: str) -> str:
    """原子地拿下一个 conflict_id 并持久化序号。

    格式：cf_<project_slug_short>_<seq:04d>
    project_slug_short 取前 8 个合规字符，够区分即可。
    """
    # project 名多为中英混合；只留 ASCII 字母数字和 _-，便于在 URL / 前端展示
    slug = "".join(
        ch for ch in project
        if ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ("0" <= ch <= "9") or ch in "_-"
    )[:8] or "x"
    n = _load_seq(project) + 1
    _save_seq(project, n)
    return f"cf_{slug}_{n:04d}"


# ---- read / write ----------------------------------------------------------

_ADAPTER = TypeAdapter(list[ConflictPair])


def load_all(project: str) -> list[ConflictPair]:
    p = _path(project)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    try:
        return _ADAPTER.validate_python(data)
    except ValidationError:
        out: list[ConflictPair] = []
        for item in data if isinstance(data, list) else []:
            try:
                out.append(ConflictPair.model_validate(item))
            except ValidationError:
                continue
        return out


def save_all(project: str, conflicts: Iterable[ConflictPair]) -> None:
    p = _path(project)
    data = [c.model_dump() for c in conflicts]
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def find_by_id(project: str, conflict_id: str) -> ConflictPair | None:
    for c in load_all(project):
        if c.conflict_id == conflict_id:
            return c
    return None


def upsert_one(project: str, conflict: ConflictPair) -> ConflictPair:
    """按 conflict_id 替换或追加。"""
    all_c = load_all(project)
    for i, existing in enumerate(all_c):
        if existing.conflict_id == conflict.conflict_id:
            all_c[i] = conflict
            save_all(project, all_c)
            return conflict
    all_c.append(conflict)
    save_all(project, all_c)
    return conflict


def delete_one(project: str, conflict_id: str) -> bool:
    all_c = load_all(project)
    left = [c for c in all_c if c.conflict_id != conflict_id]
    if len(left) == len(all_c):
        return False
    save_all(project, left)
    return True


def clear_all(project: str) -> None:
    """重跑检测前的清理；序号保持单调，不重置。"""
    p = _path(project)
    if p.exists():
        p.unlink()


def pair_key(kp_id_a: str, kp_id_b: str) -> tuple[str, str]:
    """规范化的无向对键：按字典序排序，供去重使用。"""
    return (kp_id_a, kp_id_b) if kp_id_a <= kp_id_b else (kp_id_b, kp_id_a)


def existing_pair_keys(project: str) -> set[tuple[str, str]]:
    """已有冲突的 (kp_a, kp_b) 集合；检测器用于增量合并、避免重复建档。"""
    return {pair_key(c.kp_ids[0], c.kp_ids[1]) for c in load_all(project) if len(c.kp_ids) == 2}
