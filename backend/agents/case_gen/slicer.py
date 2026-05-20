"""Step 1：需求切片 Agent（Requirement Slicer）。

职责：
  把 (question, retrieved_kps, retrieved_chunks) 切成一组**可独立生成用例**的
  FeaturePoint 列表。

关键约束（详见 docs/design/03 §5）：
  - LLM 输出必须严格符合 `SliceOutput` Schema；走 `parse_with_schema` 不做降级
  - **后端二次校验**：对 acceptance_criteria / business_rule / exception_flow 三类
    critical KP 统计覆盖率，有遗漏就把遗漏清单塞进 Prompt 让 LLM 重切
  - 重试总数（包含初次调用）≤ 3：初次 + Schema retry 1 + coverage retry 1
  - 失败不抛：返回 SliceResult，error 字段非空时交给上层决定

调用者：CaseGenPipeline.run_step1
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from backend.agents.base import AgentBase, load_prompt
from backend.core import llm as _llm_mod
from backend.core.llm import LLMConfig, SchemaValidationError, parse_with_schema
from backend.schemas.feature_point import FeaturePoint, SliceOutput
from backend.schemas.knowledge_point import KnowledgePoint


logger = logging.getLogger(__name__)


# critical 类型：这三类不允许漏切，其余类型漏掉只记 warning
CRITICAL_KP_TYPES = {"acceptance_criteria", "business_rule", "exception_flow"}

# 切片阶段最多 30 条 KP 进 Prompt（docs/design/03 §5.6 预算）
MAX_KPS_IN_PROMPT = 30
# 补充 chunks 最多 15 条
MAX_CHUNKS_IN_PROMPT = 15

DEFAULT_SLICER_SYS = (
    "你是测试需求分析专家。任务：把用户的测试需求与相关知识点切成可独立生成用例的"
    "原子功能点（FeaturePoint）。只返回合法 JSON；字段 coverage_self_check 中 "
    "uncovered_kp_ids 必须为空。"
)


@dataclass
class SliceResult:
    """Step 1 的业务产出（非 schema）。

    - slice_output: LLM 产出的原始 SliceOutput（Schema 校验通过后的）
    - uncovered_critical: 后端校验后仍未被任何 FP 引用的 critical KP
    - retries: 触发的重试次数（Schema 或 coverage）
    - llm_calls: 实际 LLM 调用次数
    - error: 非空时表示失败（调用方可以把它塞到 StepState.error）
    """
    slice_output: Optional[SliceOutput] = None
    uncovered_critical: list[str] = field(default_factory=list)
    retries: int = 0
    llm_calls: int = 0
    error: Optional[str] = None


class Slicer(AgentBase):
    name = "slicer"

    def run(
        self,
        question: str,
        kps: list[KnowledgePoint],
        chunks: Optional[list[dict]] = None,
        *,
        llm_cfg: LLMConfig,
        max_coverage_retries: int = 1,
    ) -> SliceResult:
        """把 question + kps + chunks 切成 FeaturePoint 列表。

        Parameters
        ----------
        chunks : list[dict], optional
            每条形如 {"chunk_id": "a.md::0", "source": "a.md", "text": "..."}。
            仅用作补充上下文，不参与覆盖校验。
        max_coverage_retries : int
            后端校验失败（有漏切 critical KP）时额外的 LLM 重试次数，默认 1。
        """
        result = SliceResult()
        trimmed_kps = kps[:MAX_KPS_IN_PROMPT]
        trimmed_chunks = (chunks or [])[:MAX_CHUNKS_IN_PROMPT]

        sys_prompt = load_prompt("case_gen/01_slicer.txt") or DEFAULT_SLICER_SYS
        base_messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": _build_user_prompt(
                question, trimmed_kps, trimmed_chunks,
            )},
        ]

        messages = list(base_messages)
        attempt = 0
        while True:
            attempt += 1
            try:
                raw = _llm_mod.chat(
                    messages=messages, cfg=llm_cfg,
                    temperature=0.1, json_mode=True,
                )
                result.llm_calls += 1
            except Exception as e:
                result.error = f"LLM 调用失败: {e!r}"
                return result

            try:
                out: SliceOutput = parse_with_schema(
                    raw, SliceOutput,
                    retry_cfg=llm_cfg,
                    retry_messages=messages,
                    max_retries=1,
                )
                # parse_with_schema 如果重试成功了，会自己多调用 1 次 LLM——记一笔
                # （无法精确知道它是否重试了；保守按"允许重试"加 1，这里只按实际 raw 可成功则不加）
            except SchemaValidationError as e:
                result.error = f"Schema 校验失败: {e}"
                return result

            # ---- 后端覆盖率二次校验 ----
            missing = _uncovered_critical(out, trimmed_kps)
            if not missing or attempt >= max_coverage_retries + 1:
                result.slice_output = out
                result.uncovered_critical = missing
                return result

            # 漏切 critical → 构造一条"补切"消息，重试
            result.retries += 1
            logger.info(
                "[slicer] 发现漏切 critical KP（attempt=%d, missing=%s），重试",
                attempt, missing,
            )
            messages = base_messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": _build_retry_prompt(missing, trimmed_kps)},
            ]


# ============ prompt 拼装 ===================================================

def _kp_line(kp: KnowledgePoint) -> str:
    content = (kp.content or "").replace("\n", " ").strip()
    if len(content) > 200:
        content = content[:200] + "..."
    return f"{kp.kp_id}\t{kp.type}\t{kp.module}\t{content}"


def _chunk_line(ch: dict) -> str:
    cid = ch.get("chunk_id") or ch.get("source") or "?"
    text = (ch.get("text") or "").replace("\n", " ").strip()
    if len(text) > 300:
        text = text[:300] + "..."
    return f"{cid}\t{text}"


def _build_user_prompt(
    question: str,
    kps: list[KnowledgePoint],
    chunks: list[dict],
) -> str:
    parts = [f"question: {question.strip()}", "", "kps (kp_id, type, module, content):"]
    if kps:
        parts.extend(_kp_line(kp) for kp in kps)
    else:
        parts.append("(无相关 KP)")
    parts.extend(["", "chunks (chunk_id, text):"])
    if chunks:
        parts.extend(_chunk_line(c) for c in chunks)
    else:
        parts.append("(无补充 chunk)")
    parts.extend([
        "",
        "请严格按 Schema 输出，coverage_self_check.uncovered_kp_ids 必须为空。",
    ])
    return "\n".join(parts)


def _build_retry_prompt(missing_ids: list[str], kps: list[KnowledgePoint]) -> str:
    id2kp = {kp.kp_id: kp for kp in kps}
    lines = ["你的上一轮输出漏切了以下 critical KP（必须被至少 1 个 FP 的 related_kp_ids 引用）："]
    for mid in missing_ids:
        kp = id2kp.get(mid)
        if kp:
            lines.append(f"  - {mid} ({kp.type}, {kp.module}): {kp.content[:80]}")
        else:
            lines.append(f"  - {mid}")
    lines.append("")
    lines.append("请重新输出完整的 SliceOutput（不是增量），确保：")
    lines.append("  1. feature_points 覆盖上述所有 kp_id；")
    lines.append("  2. coverage_self_check.uncovered_kp_ids 为空；")
    lines.append("  3. 其他已覆盖的 FP 可以保留不动。")
    lines.append("只返回合法 JSON。")
    return "\n".join(lines)


# ============ 后端覆盖率校验 ================================================

def _uncovered_critical(
    out: SliceOutput,
    input_kps: list[KnowledgePoint],
) -> list[str]:
    """返回"必须被引用但未被引用"的 kp_id 列表（仅 critical 类型）。"""
    covered: set[str] = set()
    for fp in out.feature_points:
        covered.update(fp.related_kp_ids)
    missing: list[str] = []
    for kp in input_kps:
        if kp.type in CRITICAL_KP_TYPES and kp.kp_id not in covered:
            missing.append(kp.kp_id)
    return missing
