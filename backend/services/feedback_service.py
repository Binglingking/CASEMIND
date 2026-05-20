"""Feedback service：封装 feedback_store 读写 + 聚合统计 + few-shot 候选选择。

路由层负责 flag guard + HTTP 映射，这里只做纯逻辑。
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from backend.core import feedback_store
from backend.core.timeutil import utc_iso_z
from backend.schemas.feedback import FeedbackKind, FeedbackRecord, TargetType


def _now_iso() -> str:
    return utc_iso_z()


# ---- 写入 ------------------------------------------------------------------

def submit(
    project: str, *,
    target_id: str,
    kind: FeedbackKind,
    target_type: TargetType = "case",
    pipeline_id: Optional[str] = None,
    module: Optional[str] = None,
    note: str = "",
    snapshot: Optional[dict] = None,
    edited_payload: Optional[dict] = None,
    user_tag: str = "",
) -> dict:
    fid = feedback_store.next_feedback_id(project)
    rec = FeedbackRecord(
        feedback_id=fid,
        target_type=target_type, target_id=target_id,
        pipeline_id=pipeline_id, module=module,
        kind=kind, note=note,
        snapshot=snapshot or {},
        edited_payload=edited_payload,
        created_at=_now_iso(),
        user_tag=user_tag,
    )
    feedback_store.append_one(project, rec)
    return rec.model_dump()


def delete(project: str, feedback_id: str) -> bool:
    return feedback_store.delete_one(project, feedback_id)


def clear(project: str) -> None:
    feedback_store.clear_all(project)


# ---- 读取 / 聚合 -----------------------------------------------------------

def list_all(project: str, *, kind: Optional[FeedbackKind] = None,
             target_id: Optional[str] = None) -> list[dict]:
    rows = feedback_store.load_all(project)
    if kind:
        rows = [r for r in rows if r.kind == kind]
    if target_id:
        rows = [r for r in rows if r.target_id == target_id]
    return [r.model_dump() for r in rows]


def summary(project: str) -> dict:
    """返回 up/down/edit 三项计数 + 按模块/按 kind 聚合。"""
    rows = feedback_store.load_all(project)
    kc = Counter(r.kind for r in rows)
    mc: dict[str, dict[str, int]] = {}
    for r in rows:
        m = r.module or "_none_"
        mc.setdefault(m, {"up": 0, "down": 0, "edit": 0})
        mc[m][r.kind] = mc[m].get(r.kind, 0) + 1
    return {
        "total": len(rows),
        "by_kind": {"up": kc.get("up", 0), "down": kc.get("down", 0),
                    "edit": kc.get("edit", 0)},
        "by_module": mc,
    }


# ---- Few-shot 选择（给 CaseGenerator 用） ----------------------------------

def select_positive_examples(
    project: str, *,
    module: Optional[str] = None,
    limit: int = 3,
) -> list[dict]:
    """取 kind=up 且 snapshot 非空的记录，作为生成 few-shot 的正例。

    同一 target_id 只保留最新一条；按 created_at 逆序排；可按模块过滤。
    返回值是 snapshot dict 列表（即用例本身），方便直接拼进 prompt。
    """
    rows = feedback_store.load_all(project)
    ups = [r for r in rows if r.kind == "up" and r.snapshot]
    if module:
        ups = [r for r in ups if (r.module or "") == module]

    # 同 target_id 只保留最新
    latest: dict[str, FeedbackRecord] = {}
    for r in ups:
        prev = latest.get(r.target_id)
        if prev is None or r.created_at > prev.created_at:
            latest[r.target_id] = r
    # 按时间逆序
    picked = sorted(latest.values(), key=lambda r: r.created_at, reverse=True)[:limit]
    return [r.snapshot for r in picked]
