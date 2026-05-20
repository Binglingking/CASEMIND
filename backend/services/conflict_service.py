"""Conflict service：封装 ConflictDetector 调用 + conflict_store 读写，
供 api/routes_conflict.py 使用。该层只转发，保持路由薄。
"""
from __future__ import annotations

from typing import Optional

from backend.agents.conflict_detector import ConflictDetector, DetectStats
from backend.core import conflict_store
from backend.core.llm import LLMConfig
from backend.core.timeutil import utc_iso_z
from backend.schemas.conflict import ConflictPair, Resolution


def _now_iso() -> str:
    return utc_iso_z()


def run_detection(
    project: str,
    cfg: LLMConfig,
    *,
    sim_low: float = 0.75,
    sim_high: float = 0.99,
    modules: Optional[list[str]] = None,
) -> dict:
    """运行一次检测，返回 `{new_conflicts, stats}`。"""
    detector = ConflictDetector(project)
    new_conflicts, stats = detector.detect(
        cfg, sim_low=sim_low, sim_high=sim_high, modules=modules,
    )
    return {
        "new_conflicts": [c.model_dump() for c in new_conflicts],
        "stats": {
            "total_kps": stats.total_kps,
            "eligible_kps": stats.eligible_kps,
            "candidate_pairs": stats.candidate_pairs,
            "judged_pairs": stats.judged_pairs,
            "new_conflicts": stats.new_conflicts,
            "skipped_existing": stats.skipped_existing,
        },
    }


def list_all(project: str) -> list[dict]:
    return [c.model_dump() for c in conflict_store.load_all(project)]


def resolve(
    project: str, conflict_id: str,
    *, resolution: Resolution, note: str = "",
) -> dict:
    """标注冲突处置。找不到抛 FileNotFoundError，交由路由映射成 404。"""
    cp = conflict_store.find_by_id(project, conflict_id)
    if cp is None:
        raise FileNotFoundError(f"conflict not found: {conflict_id}")
    updated = cp.model_copy(update={
        "resolution": resolution,
        "resolution_note": note,
        "resolved_at": _now_iso() if resolution != "unresolved" else None,
    })
    conflict_store.upsert_one(project, updated)
    return updated.model_dump()


def delete(project: str, conflict_id: str) -> bool:
    return conflict_store.delete_one(project, conflict_id)


def clear(project: str) -> None:
    conflict_store.clear_all(project)
