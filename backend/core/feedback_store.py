"""反馈记录（FeedbackRecord）持久化。

文件布局：

    memory/<project>/
    ├── feedback.json           # FeedbackRecord[]
    └── feedback.seq.json       # {"seq": <int>}

职责：纯 IO + 序号；聚合/过滤/few-shot 选择逻辑放 services/feedback_service.py。
写入一律原子（先 .tmp 再 rename）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from pydantic import TypeAdapter, ValidationError

from backend.core.project import project_manager
from backend.schemas.feedback import FeedbackRecord


FEEDBACK_FILE = "feedback.json"
SEQ_FILE = "feedback.seq.json"


# ---- paths -----------------------------------------------------------------

def _path(project: str) -> Path:
    return project_manager.mem_dir(project) / FEEDBACK_FILE


def _seq_path(project: str) -> Path:
    return project_manager.mem_dir(project) / SEQ_FILE


# ---- sequence --------------------------------------------------------------

def _project_slug(project: str) -> str:
    slug = "".join(
        ch for ch in project
        if ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ("0" <= ch <= "9") or ch in "_-"
    )[:8]
    return slug or "x"


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


def next_feedback_id(project: str) -> str:
    """fb_<slug>_<seq:06d>"""
    n = _load_seq(project) + 1
    _save_seq(project, n)
    return f"fb_{_project_slug(project)}_{n:06d}"


# ---- read / write ----------------------------------------------------------

_ADAPTER = TypeAdapter(list[FeedbackRecord])


def load_all(project: str) -> list[FeedbackRecord]:
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
        out: list[FeedbackRecord] = []
        for item in data if isinstance(data, list) else []:
            try:
                out.append(FeedbackRecord.model_validate(item))
            except ValidationError:
                continue
        return out


def save_all(project: str, records: Iterable[FeedbackRecord]) -> None:
    p = _path(project)
    data = [r.model_dump() for r in records]
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def find_by_id(project: str, feedback_id: str) -> Optional[FeedbackRecord]:
    for r in load_all(project):
        if r.feedback_id == feedback_id:
            return r
    return None


def append_one(project: str, record: FeedbackRecord) -> FeedbackRecord:
    all_r = load_all(project)
    all_r.append(record)
    save_all(project, all_r)
    return record


def delete_one(project: str, feedback_id: str) -> bool:
    all_r = load_all(project)
    left = [r for r in all_r if r.feedback_id != feedback_id]
    if len(left) == len(all_r):
        return False
    save_all(project, left)
    return True


def clear_all(project: str) -> None:
    """清空反馈；序号保持单调，不重置。"""
    p = _path(project)
    if p.exists():
        p.unlink()


# ---- 查询辅助（薄，给 service 用） -----------------------------------------

def find_by_target(project: str, target_id: str) -> list[FeedbackRecord]:
    return [r for r in load_all(project) if r.target_id == target_id]


def find_latest_per_target(project: str) -> dict[str, FeedbackRecord]:
    """同一 target_id 只保留最新一条（按 created_at 字典序）。"""
    latest: dict[str, FeedbackRecord] = {}
    for r in load_all(project):
        prev = latest.get(r.target_id)
        if prev is None or r.created_at > prev.created_at:
            latest[r.target_id] = r
    return latest
