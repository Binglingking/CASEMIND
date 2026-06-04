"""Stage 5: generate inferred KP candidates from legacy cases/XMind.

The new flow summarizes by uploaded file. Only uncertain summaries should be
shown for human review; high-confidence summaries wait in a build queue and are
promoted during memory build.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from pydantic import BaseModel, Field

from backend.agents.base import load_prompt
from backend.agents.legacy_analyzer.schemas import (
    AggregatedSignals,
    ExtractedSignal,
    NormalizedBatch,
)
from backend.core import llm as _llm_mod
from backend.core.legacy import legacy_store
from backend.core.llm import LLMConfig, SchemaValidationError, parse_with_schema
from backend.core.timeutil import utc_iso_z
from backend.schemas.inferred_kp import InferredKnowledgePoint, InferredSource

logger = logging.getLogger(__name__)

MAX_SIGNALS_PER_BATCH = 80
CONFIDENCE_AUTO_ACCEPT = 0.90


class _SummaryItem(BaseModel):
    type: str
    content: str = Field(..., max_length=300)
    module: str
    aliases: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    reasoning: str = ""
    source_summary: str = ""
    aggregated_signal_indices: list[int] = Field(default_factory=list)


class _SummaryOutput(BaseModel):
    items: list[_SummaryItem] = Field(default_factory=list)


def _inferred_id(signal: ExtractedSignal) -> str:
    raw = (
        signal.type + "|" + signal.module + "|" +
        signal.source_kind + "|" + signal.source_ref + "|" +
        signal.content
    ).encode("utf-8")
    return f"IKP_{hashlib.sha1(raw).hexdigest()[:8]}"


def _inferred_id_from_summary(item: _SummaryItem, file_key: str, idx: int) -> str:
    raw = (file_key + "|" + item.type + "|" + item.module + "|" + item.content).encode("utf-8")
    return f"IKP_{hashlib.sha1(raw).hexdigest()[:8]}"


def _build_source_indexes(batch: NormalizedBatch) -> tuple[dict, dict]:
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
    return case_index, leaf_index


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
    if signal.source_kind == "xmind":
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


def _signal_file_key(
    signal: ExtractedSignal,
    case_index: dict[str, dict],
    leaf_index: dict[str, dict],
) -> str:
    src = _build_source(signal, case_index, leaf_index)
    if src is None:
        return "unknown:summarized"
    return f"{src.kind}:{src.file_id}:{src.file}"


def _apply_review_status(
    items: list[InferredKnowledgePoint],
    *,
    auto_accept: bool,
) -> list[InferredKnowledgePoint]:
    for ikp in items:
        if auto_accept and ikp.confidence >= CONFIDENCE_AUTO_ACCEPT:
            ikp.auto_accepted = True
            ikp.review_status = "ready_to_build"
            ikp.reviewed_at = utc_iso_z()
            ikp.reviewed_by = "system"
        else:
            ikp.auto_accepted = False
            ikp.review_status = "pending_review"
    return items


def to_inferred_kps(
    aggregated: AggregatedSignals,
    batch: NormalizedBatch,
) -> list[InferredKnowledgePoint]:
    case_index, leaf_index = _build_source_indexes(batch)
    now = utc_iso_z()
    out: list[InferredKnowledgePoint] = []
    for s in aggregated.items:
        src = _build_source(s, case_index, leaf_index)
        if src is None:
            continue
        out.append(InferredKnowledgePoint(
            inferred_id=_inferred_id(s),
            type=s.type,
            content=s.content,
            module=s.module,
            aliases=s.aliases,
            source=src,
            aggregated_from=[],
            source_summary="",
            confidence=s.confidence,
            reasoning=s.reasoning,
            auto_accepted=False,
            extracted_at=now,
            review_status="pending_review",
        ))
    return out


def _build_summarize_user_prompt(signals: list[ExtractedSignal], batch: NormalizedBatch) -> str:
    lines = [
        f"请通读同一个历史用例/XMind文件内的 {len(signals)} 条信号，"
        "合并去重后输出少量文件级总结知识点。只总结能稳定反映需求/规则/约束的内容，"
        "不要逐条用例或逐个节点复述。\n"
    ]
    case_index, leaf_index = _build_source_indexes(batch)
    for i, s in enumerate(signals):
        src = _build_source(s, case_index, leaf_index)
        source_hint = ""
        if src:
            source_hint = f" file={src.file}"
            if src.case_id:
                source_hint += f" case={src.case_id} row={src.case_row}"
            if src.node_path:
                source_hint += f" path={' > '.join(src.node_path)}"
        lines.append(
            f"[{i}] type={s.type} module={s.module} conf={s.confidence:.2f}"
            f" source={s.source_kind}:{s.source_ref}{source_hint}\n"
            f"content: {s.content}\n"
            f"reasoning: {s.reasoning or '(empty)'}\n"
        )
    return "\n".join(lines)


def _run_summarize_batch(
    signals: list[ExtractedSignal],
    batch: NormalizedBatch,
    *,
    cfg: LLMConfig,
) -> tuple[list[_SummaryItem], int, Optional[str]]:
    if not signals:
        return [], 0, None

    sys_prompt = load_prompt("legacy/05_summarize_kps.txt")
    if not sys_prompt:
        return [], 0, "prompt missing: legacy/05_summarize_kps.txt"

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": _build_summarize_user_prompt(signals, batch)},
    ]

    try:
        raw = _llm_mod.chat(messages=messages, cfg=cfg, temperature=0.15, json_mode=True)
    except Exception as e:  # noqa: BLE001
        return [], 1, f"LLM call failed: {e!r}"

    try:
        parsed = parse_with_schema(
            raw, _SummaryOutput,
            retry_cfg=cfg, retry_messages=messages, max_retries=1,
        )
    except SchemaValidationError as e:
        return [], 1, f"schema validation failed: {e}"

    valid: list[_SummaryItem] = []
    for item in parsed.items:
        item.aggregated_signal_indices = [
            j for j in item.aggregated_signal_indices
            if 0 <= j < len(signals)
        ]
        if item.content.strip():
            valid.append(item)
    return valid, 1, None


def _summary_to_ikp(
    item: _SummaryItem,
    signals: list[ExtractedSignal],
    case_index: dict[str, dict],
    leaf_index: dict[str, dict],
    file_key: str,
    idx: int,
    now: str,
) -> InferredKnowledgePoint:
    aggregated_sources: list[InferredSource] = []
    for j in item.aggregated_signal_indices:
        src = _build_source(signals[j], case_index, leaf_index)
        if src is not None:
            aggregated_sources.append(src)

    if not aggregated_sources:
        for sig in signals:
            src = _build_source(sig, case_index, leaf_index)
            if src is not None:
                aggregated_sources.append(src)
                break

    main_source = aggregated_sources[0] if aggregated_sources else InferredSource(
        kind="case",
        file="aggregated",
        file_id="summarized",
    )

    return InferredKnowledgePoint(
        inferred_id=_inferred_id_from_summary(item, file_key, idx),
        type=item.type,
        content=item.content,
        module=item.module,
        aliases=item.aliases,
        source=main_source,
        aggregated_from=aggregated_sources,
        source_summary=item.source_summary,
        confidence=item.confidence,
        reasoning=item.reasoning,
        auto_accepted=False,
        extracted_at=now,
        review_status="pending_review",
    )


def _fallback_direct(
    signals: list[ExtractedSignal],
    case_index: dict[str, dict],
    leaf_index: dict[str, dict],
    now: str,
) -> list[InferredKnowledgePoint]:
    out: list[InferredKnowledgePoint] = []
    for s in signals:
        src = _build_source(s, case_index, leaf_index)
        if src is None:
            continue
        out.append(InferredKnowledgePoint(
            inferred_id=_inferred_id(s),
            type=s.type,
            content=s.content,
            module=s.module,
            aliases=s.aliases,
            source=src,
            aggregated_from=[src],
            source_summary="LLM summary failed; retained original extracted signal.",
            confidence=s.confidence,
            reasoning=s.reasoning,
            auto_accepted=False,
            extracted_at=now,
            review_status="pending_review",
        ))
    return out


def summarize_signals(
    aggregated: AggregatedSignals,
    batch: NormalizedBatch,
    *,
    cfg: LLMConfig,
    auto_accept: bool = False,
) -> tuple[list[InferredKnowledgePoint], int, list[str]]:
    if not aggregated.items:
        return [], 0, []

    case_index, leaf_index = _build_source_indexes(batch)
    now = utc_iso_z()

    by_file: dict[str, list[ExtractedSignal]] = {}
    for s in aggregated.items:
        by_file.setdefault(_signal_file_key(s, case_index, leaf_index), []).append(s)

    all_ikps: list[InferredKnowledgePoint] = []
    total_calls = 0
    errors: list[str] = []

    for file_key, signals in by_file.items():
        chunks = [
            signals[i:i + MAX_SIGNALS_PER_BATCH]
            for i in range(0, len(signals), MAX_SIGNALS_PER_BATCH)
        ]
        for chunk_idx, chunk_signals in enumerate(chunks):
            items, calls, err = _run_summarize_batch(chunk_signals, batch, cfg=cfg)
            total_calls += calls
            if err:
                errors.append(f"[summarize {file_key}#{chunk_idx}] {err}")
                all_ikps.extend(_fallback_direct(chunk_signals, case_index, leaf_index, now))
                continue

            for item_idx, item in enumerate(items):
                all_ikps.append(_summary_to_ikp(
                    item, chunk_signals, case_index, leaf_index,
                    file_key, item_idx, now,
                ))

    all_ikps = _apply_review_status(all_ikps, auto_accept=auto_accept)
    ready_count = sum(1 for ikp in all_ikps if ikp.review_status == "ready_to_build")
    pending_count = sum(1 for ikp in all_ikps if ikp.review_status == "pending_review")
    logger.info(
        "[Stage 5] file summaries generated: signals=%d summaries=%d ready_to_build=%d pending_review=%d",
        len(aggregated.items), len(all_ikps), ready_count, pending_count,
    )
    return all_ikps, total_calls, errors


def persist(project: str, items: list[InferredKnowledgePoint]) -> None:
    legacy_store.upsert_inferred_kps(project, items)
