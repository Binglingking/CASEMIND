"""Stage 5：反哺候选生成 + AI 智能归纳（Stage 4.5）。

两种模式：
  1) 原始模式（to_inferred_kps）：1:1 转换，每个 ExtractedSignal → 一个 IKP
  2) AI 归纳模式（summarize_signals）：按模块分组，LLM 全局阅读后合并去重，
     生成少量高价值知识点；高置信度自动通过，低置信度推送审核。

置信度分级规则：
  - confidence ≥ 0.90 → auto_accepted=True, review_status="auto_accepted"
  - confidence < 0.80  → review_status="pending"（推送到审核队列）
  - 0.80 ~ 0.90       → review_status="pending"（中等，仍需审核）
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from backend.agents.base import load_prompt
from backend.agents.legacy_analyzer.schemas import (
    AggregatedSignals,
    ExtractedSignal,
    NormalizedBatch,
    NormalizedCaseUnit,
    NormalizedXMindLeaf,
)
from backend.core import llm as _llm_mod
from backend.core.legacy import legacy_store
from backend.core.llm import LLMConfig, SchemaValidationError, parse_with_schema
from backend.core.timeutil import utc_iso_z
from backend.schemas.inferred_kp import (
    InferredKnowledgePoint,
    InferredSource,
)

logger = logging.getLogger(__name__)

# 单模块信号数上限，超出则拆批
MAX_SIGNALS_PER_BATCH = 80

# 置信度阈值
CONFIDENCE_AUTO_ACCEPT = 0.90   # ≥ 此值自动通过
CONFIDENCE_LOW = 0.80           # < 此值标记为低置信度


# ---- LLM 输出 Schema -------------------------------------------------------

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


# ---- 内部辅助 --------------------------------------------------------------

def _inferred_id(signal: ExtractedSignal) -> str:
    raw = (
        signal.type + "|" + signal.module + "|" +
        signal.source_kind + "|" + signal.source_ref + "|" +
        signal.content
    ).encode("utf-8")
    return f"IKP_{hashlib.sha1(raw).hexdigest()[:8]}"


def _inferred_id_from_summary(item: _SummaryItem, module: str, idx: int) -> str:
    raw = (item.type + "|" + module + "|" + item.content).encode("utf-8")
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


def _build_source_indexes(batch: NormalizedBatch) -> tuple[dict, dict]:
    """构建 case_index 和 leaf_index，供 _build_source 使用。"""
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


def _apply_auto_accept(items: list[InferredKnowledgePoint]) -> list[InferredKnowledgePoint]:
    """根据置信度自动分级：高置信度自动通过，其余保留 pending。"""
    for ikp in items:
        if ikp.confidence >= CONFIDENCE_AUTO_ACCEPT:
            ikp.auto_accepted = True
            ikp.review_status = "auto_accepted"
            ikp.reviewed_at = utc_iso_z()
            ikp.reviewed_by = "system"
        else:
            ikp.auto_accepted = False
            ikp.review_status = "pending"
    return items


# ---- 原始模式（1:1 转换） ---------------------------------------------------

def to_inferred_kps(
    aggregated: AggregatedSignals,
    batch: NormalizedBatch,
) -> list[InferredKnowledgePoint]:
    """原始模式：每条 ExtractedSignal 转为一个 IKP（不聚合、不总结）。"""
    case_index, leaf_index = _build_source_indexes(batch)

    out: list[InferredKnowledgePoint] = []
    now = utc_iso_z()
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
            review_status="pending",
        ))
    return out


# ---- AI 归纳模式 -----------------------------------------------------------

def _build_summarize_user_prompt(
    signals: list[ExtractedSignal],
    batch: NormalizedBatch,
) -> str:
    """构造 AI 总结的 user prompt：列出所有信号 + 关键上下文。"""
    lines = [f"共 {len(signals)} 条信号，请全局阅读后合并去重，输出精炼知识点。\n"]
    for i, s in enumerate(signals):
        lines.append(
            f"[{i}] type={s.type} module={s.module} conf={s.confidence:.2f} "
            f"source={s.source_kind}:{s.source_ref}\n"
            f"    content: {s.content}\n"
            f"    reasoning: {s.reasoning or '(无)'}\n"
        )
    return "\n".join(lines)


def _run_summarize_batch(
    signals: list[ExtractedSignal],
    batch: NormalizedBatch,
    *,
    cfg: LLMConfig,
) -> tuple[list[_SummaryItem], int, Optional[str]]:
    """调用 LLM 做一批信号的归纳总结。

    Returns (summary_items, llm_calls, error)
    """
    if not signals:
        return [], 0, None

    sys_prompt = load_prompt("legacy/05_summarize_kps.txt")
    if not sys_prompt:
        return [], 0, "prompt 文件缺失: legacy/05_summarize_kps.txt"

    user_prompt = _build_summarize_user_prompt(signals, batch)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw = _llm_mod.chat(
            messages=messages, cfg=cfg,
            temperature=0.15, json_mode=True,
        )
    except Exception as e:
        return [], 1, f"LLM 调用失败: {e!r}"

    try:
        parsed = parse_with_schema(
            raw, _SummaryOutput,
            retry_cfg=cfg, retry_messages=messages, max_retries=1,
        )
    except SchemaValidationError as e:
        return [], 1, f"Schema 校验失败: {e}"

    # 校验 aggregated_signal_indices 是否在范围内
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
    idx: int,
    now: str,
) -> InferredKnowledgePoint:
    """将一条 AI 总结结果转为 InferredKnowledgePoint。"""
    # 收集所有引用的 source
    aggregated_sources: list[InferredSource] = []
    for j in item.aggregated_signal_indices:
        sig = signals[j]
        src = _build_source(sig, case_index, leaf_index)
        if src is not None:
            aggregated_sources.append(src)

    # 主 source 取第一个有效的
    main_source = aggregated_sources[0] if aggregated_sources else InferredSource(
        kind="case", file="aggregated", file_id="summarized",
    )

    inferred_id = _inferred_id_from_summary(item, item.module, idx)

    return InferredKnowledgePoint(
        inferred_id=inferred_id,
        type=item.type,
        content=item.content,
        module=item.module,
        aliases=item.aliases,
        source=main_source,
        aggregated_from=aggregated_sources,
        source_summary=item.source_summary,
        confidence=item.confidence,
        reasoning=item.reasoning,
        auto_accepted=False,  # 后面 _apply_auto_accept 统一设置
        extracted_at=now,
        review_status="pending",
    )


def summarize_signals(
    aggregated: AggregatedSignals,
    batch: NormalizedBatch,
    *,
    cfg: LLMConfig,
) -> tuple[list[InferredKnowledgePoint], int, list[str]]:
    """AI 归纳模式：按模块分组，LLM 全局阅读后合并去重生成高价值知识点。

    Returns (ikps, llm_calls, errors)
    """
    if not aggregated.items:
        return [], 0, []

    case_index, leaf_index = _build_source_indexes(batch)
    now = utc_iso_z()

    # 按模块分组
    by_module: dict[str, list[tuple[int, ExtractedSignal]]] = {}
    for i, s in enumerate(aggregated.items):
        mod = s.module or "_未分类_"
        by_module.setdefault(mod, []).append((i, s))

    all_ikps: list[InferredKnowledgePoint] = []
    total_calls = 0
    errors: list[str] = []

    for module, indexed_signals in by_module.items():
        signals = [s for _, s in indexed_signals]
        indices = [i for i, _ in indexed_signals]
        total = len(signals)

        # 如果模块信号太少（<3 条），跳过 AI 总结，直接用原始模式
        if total < 3:
            logger.info(
                "[Stage 4.5] 模块 %s 仅 %d 条信号，跳过 AI 总结，使用原始转换",
                module, total,
            )
            for s in signals:
                src = _build_source(s, case_index, leaf_index)
                if src is None:
                    continue
                all_ikps.append(InferredKnowledgePoint(
                    inferred_id=_inferred_id(s),
                    type=s.type, content=s.content, module=s.module,
                    aliases=s.aliases, source=src,
                    aggregated_from=[], source_summary="",
                    confidence=s.confidence, reasoning=s.reasoning,
                    auto_accepted=False,
                    extracted_at=now, review_status="pending",
                ))
            continue

        # 拆分大模块
        chunks = [signals[i:i + MAX_SIGNALS_PER_BATCH]
                  for i in range(0, total, MAX_SIGNALS_PER_BATCH)]

        for chunk_idx, chunk_signals in enumerate(chunks):
            items, calls, err = _run_summarize_batch(
                chunk_signals, batch, cfg=cfg,
            )
            total_calls += calls
            if err:
                errors.append(f"[summarize {module}#{chunk_idx}] {err}")
                logger.warning(
                    "[Stage 4.5] 模块 %s 批次 %d LLM 失败，回退原始转换: %s",
                    module, chunk_idx, err,
                )
                # 失败回退：该批信号用原始模式
                for s in chunk_signals:
                    src = _build_source(s, case_index, leaf_index)
                    if src is None:
                        continue
                    all_ikps.append(InferredKnowledgePoint(
                        inferred_id=_inferred_id(s),
                        type=s.type, content=s.content, module=s.module,
                        aliases=s.aliases, source=src,
                        aggregated_from=[], source_summary="",
                        confidence=s.confidence, reasoning=s.reasoning,
                        auto_accepted=False,
                        extracted_at=now, review_status="pending",
                    ))
                continue

            for item_idx, item in enumerate(items):
                ikp = _summary_to_ikp(
                    item, chunk_signals, case_index, leaf_index,
                    item_idx, now,
                )
                all_ikps.append(ikp)

            logger.info(
                "[Stage 4.5] 模块 %s 批次 %d: %d 条信号 → %d 条知识点",
                module, chunk_idx, len(chunk_signals), len(items),
            )

    # 统一应用置信度分级
    all_ikps = _apply_auto_accept(all_ikps)

    auto_count = sum(1 for ikp in all_ikps if ikp.review_status == "auto_accepted")
    pending_count = sum(1 for ikp in all_ikps if ikp.review_status == "pending")
    logger.info(
        "[Stage 4.5] 归纳完成: %d 条信号 → %d 条知识点 "
        "(auto_accepted=%d, pending=%d)",
        len(aggregated.items), len(all_ikps), auto_count, pending_count,
    )

    return all_ikps, total_calls, errors


# ---- 持久化 ----------------------------------------------------------------

def persist(
    project: str,
    items: list[InferredKnowledgePoint],
) -> None:
    legacy_store.upsert_inferred_kps(project, items)
