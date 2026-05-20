"""Stage 5：反哺候选生成（纯转换）。

把 Stage 4 聚合后的 ExtractedSignal 转成 InferredKnowledgePoint，
补全溯源细节（case_row / node_path）后写入 legacy_store.inferred_kps.json。
**永不**自动合入 knowledge_points.json：要靠 Memory 页面人工审核。
"""
from __future__ import annotations

import hashlib

from backend.agents.legacy_analyzer.schemas import (
    AggregatedSignals,
    ExtractedSignal,
    NormalizedBatch,
)
from backend.core.legacy import legacy_store
from backend.core.timeutil import utc_iso_z
from backend.schemas.inferred_kp import (
    InferredKnowledgePoint,
    InferredSource,
)


def _inferred_id(signal: ExtractedSignal) -> str:
    raw = (
        signal.type + "|" + signal.module + "|" +
        signal.source_kind + "|" + signal.source_ref + "|" +
        signal.content
    ).encode("utf-8")
    return f"IKP_{hashlib.sha1(raw).hexdigest()[:8]}"


def _build_source(
    signal: ExtractedSignal,
    case_index: dict[str, dict],
    leaf_index: dict[str, dict],
) -> InferredSource | None:
    if signal.source_kind == "case":
        meta = case_index.get(signal.source_ref)
        if not meta:
            return None
        return InferredSource(
            kind="case",
            file=meta["source_file"],
            file_id=meta["file_id"],
            case_id=signal.source_ref,
            case_row=meta["source_row"],
        )
    elif signal.source_kind == "xmind":
        meta = leaf_index.get(signal.source_ref)
        if not meta:
            return None
        return InferredSource(
            kind="xmind",
            file=meta["source_file"],
            file_id=meta["file_id"],
            node_id=signal.source_ref,
            node_path=meta["path"],
        )
    return None


def to_inferred_kps(
    aggregated: AggregatedSignals,
    batch: NormalizedBatch,
) -> list[InferredKnowledgePoint]:
    case_index = {
        c.case_id: {
            "source_file": c.source_file,
            "file_id": c.file_id,
            "source_row": c.source_row,
        }
        for c in batch.case_units
    }
    leaf_index = {
        n.node_id: {
            "source_file": n.source_file,
            "file_id": n.file_id,
            "path": n.path,
        }
        for n in batch.xmind_leaves
    }

    out: list[InferredKnowledgePoint] = []
    now = utc_iso_z()
    for s in aggregated.items:
        src = _build_source(s, case_index, leaf_index)
        if src is None:
            # 溯源信息丢失则丢弃，不允许无源候选写入
            continue
        out.append(InferredKnowledgePoint(
            inferred_id=_inferred_id(s),
            type=s.type,
            content=s.content,
            module=s.module,
            aliases=s.aliases,
            source=src,
            confidence=s.confidence,
            reasoning=s.reasoning,
            extracted_at=now,
            review_status="pending",
        ))
    return out


def persist(
    project: str,
    items: list[InferredKnowledgePoint],
) -> None:
    legacy_store.upsert_inferred_kps(project, items)
