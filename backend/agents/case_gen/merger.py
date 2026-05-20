"""Step 3：合并去重 + 跨 FP 集成用例补充（Merger Agent）。

两阶段：
  1. **本地代码去重** —— BGE embedding + Union-Find 聚类。相似度 ≥ sim_threshold
     的用例视为重复；每簇保留 confidence 最高的一条，其它 case 的 source_refs
     合并到保留 case，减轻 validator 的追溯负担。
  2. **LLM 集成用例补充** —— 只负责跨 ≥2 个 FP 的集成场景。
     模型输出 needs_review=true + confidence≤0.7，交由前端二次确认。

失败策略：
  - 去重阶段任何异常（embedding 加载失败等）→ 跳过去重，保留全部 case
  - LLM 阶段失败 → 不补集成用例，merged_cases 仍然输出

调用者：CaseGenPipeline.run_step3
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from pydantic import BaseModel, Field

from backend.agents.base import AgentBase, load_prompt
from backend.core import embeddings as _emb_mod
from backend.core import llm as _llm_mod
from backend.core.llm import LLMConfig, SchemaValidationError, parse_with_schema
from backend.schemas.feature_point import FeaturePoint
from backend.schemas.test_case import DedupeEntry, MergeOutput, SourceRef, TestCase


logger = logging.getLogger(__name__)


DEFAULT_SIM_THRESHOLD = 0.92

DEFAULT_MERGER_SYS = (
    "你是测试架构师。基于已生成的单功能点用例，识别并补充跨功能点集成测试用例。"
    "只返回合法 JSON。"
)


class _IntegrationOutput(BaseModel):
    """LLM 集成用例产出的严格 schema（匹配 prompts/case_gen/03_merger.txt）。"""
    integration_cases: list[TestCase] = Field(default_factory=list)
    rationale: str = ""


@dataclass
class MergeResult:
    """Step 3 的运行产出（非 schema）。"""
    merged: MergeOutput
    dedupe_skipped: bool = False          # embedding 不可用时为 True
    integration_skipped: bool = False     # LLM 失败或显式跳过时为 True
    llm_calls: int = 0
    integration_raw_count: int = 0        # LLM 产出但被过滤前的条数
    integration_filtered: list[str] = field(default_factory=list)  # 被过滤的 case_id
    error: Optional[str] = None


class Merger(AgentBase):
    name = "merger"

    def run(
        self,
        cases: list[TestCase],
        feature_points: list[FeaturePoint],
        allowed_kp_ids: set[str],
        *,
        llm_cfg: LLMConfig,
        sim_threshold: float = DEFAULT_SIM_THRESHOLD,
        skip_integration: bool = False,
        allowed_chunk_ids: Optional[set[str]] = None,
    ) -> MergeResult:
        """先本地去重，再让 LLM 补集成用例。

        Parameters
        ----------
        cases : list[TestCase]
            Step 2 汇总的全部用例。
        feature_points : list[FeaturePoint]
            供 LLM 识别跨 FP 场景。
        allowed_kp_ids : set[str]
            合法的 kp_id 集合——LLM 若引用了不在此集合里的 kp，用例被丢弃。
        skip_integration : bool
            True 时跳过 LLM 调用（用于 UI 上用户明确表示"只去重"的场景）。
        allowed_chunk_ids : set[str], optional
            合法的 chunk_id 集合；不提供时只用 kp_id 校验。
        """
        allowed_chunk_ids = allowed_chunk_ids or set()

        # ---- 阶段 1：本地去重 ------------------------------------------------
        try:
            kept, dedupe_log = _dedupe_cases(cases, sim_threshold=sim_threshold)
            dedupe_skipped = False
        except Exception as e:
            logger.warning("[merger] 本地去重失败，跳过去重阶段: %r", e)
            kept = list(cases)
            dedupe_log = []
            dedupe_skipped = True

        merged_output = MergeOutput(
            merged_cases=list(kept),
            dedupe_log=dedupe_log,
            integration_added=[],
        )
        result = MergeResult(merged=merged_output, dedupe_skipped=dedupe_skipped)

        # ---- 阶段 2：LLM 集成用例 --------------------------------------------
        if skip_integration or not feature_points:
            result.integration_skipped = True
            return result

        try:
            integration, raw_count, filtered = self._propose_integration(
                feature_points=feature_points,
                existing_cases=kept,
                allowed_kp_ids=allowed_kp_ids,
                allowed_chunk_ids=allowed_chunk_ids,
                llm_cfg=llm_cfg,
            )
            result.llm_calls += 1
            result.integration_raw_count = raw_count
            result.integration_filtered = filtered
        except Exception as e:
            logger.warning("[merger] 集成用例 LLM 调用失败: %r", e)
            result.integration_skipped = True
            result.error = f"集成用例生成失败: {e!r}"
            return result

        if integration:
            merged_output.merged_cases.extend(integration)
            merged_output.integration_added = [c.case_id for c in integration]
        return result

    # ---- 集成用例：调 LLM + 严格过滤 -----------------------------------------

    def _propose_integration(
        self,
        *,
        feature_points: list[FeaturePoint],
        existing_cases: list[TestCase],
        allowed_kp_ids: set[str],
        allowed_chunk_ids: set[str],
        llm_cfg: LLMConfig,
    ) -> tuple[list[TestCase], int, list[str]]:
        sys_prompt = load_prompt("case_gen/03_merger.txt") or DEFAULT_MERGER_SYS
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": _build_merger_user_prompt(
                feature_points, existing_cases, allowed_kp_ids,
            )},
        ]

        raw = _llm_mod.chat(
            messages=messages, cfg=llm_cfg,
            temperature=0.3, json_mode=True,
        )
        try:
            out: _IntegrationOutput = parse_with_schema(
                raw, _IntegrationOutput,
                retry_cfg=llm_cfg,
                retry_messages=messages,
                max_retries=1,
            )
        except SchemaValidationError as e:
            raise RuntimeError(f"集成用例 Schema 校验失败: {e}") from e

        valid_fp_ids = {fp.fp_id for fp in feature_points}
        filtered_out: list[str] = []
        valid: list[TestCase] = []
        for c in out.integration_cases:
            reason = _validate_integration_case(
                c, valid_fp_ids, allowed_kp_ids, allowed_chunk_ids,
            )
            if reason:
                logger.info("[merger] 丢弃集成用例 %s: %s", c.case_id, reason)
                filtered_out.append(c.case_id)
                continue
            # 强制标记——即便 LLM 忘了设
            c.generated_by = "merger_agent"
            c.needs_review = True
            if c.confidence > 0.7:
                c.confidence = 0.7
            valid.append(c)
        return valid, len(out.integration_cases), filtered_out


# ============ 本地去重（embedding + Union-Find） ============================

def _case_embed_text(c: TestCase) -> str:
    """把一条 case 拍扁成一段文本，给 embedding 模型用。

    关注点：标题 + 类别 + 步骤动作序列 + 期望结果。
    排除：source_refs/case_id 等元数据——我们只想判断"业务语义是否重复"。
    """
    actions = " ".join(s.action for s in c.steps)
    return f"{c.title} | {c.category} | {actions} | {c.expected_result}"


def _dedupe_cases(
    cases: list[TestCase],
    *,
    sim_threshold: float,
) -> tuple[list[TestCase], list[DedupeEntry]]:
    """Union-Find 聚类 + 保留 confidence 最高的。"""
    n = len(cases)
    if n <= 1:
        return list(cases), []

    vecs = _emb_mod.embed([_case_embed_text(c) for c in cases])
    # BGE 默认返回 L2-normalized；点积即 cosine。
    sim = vecs @ vecs.T

    parent = list(range(n))
    # 记录每对并簇时的 similarity，用于 dedupe_log
    pair_sim: dict[tuple[int, int], float] = {}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int, s: float) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        parent[ra] = rb
        pair_sim[(min(a, b), max(a, b))] = float(s)

    for i in range(n):
        for j in range(i + 1, n):
            if float(sim[i, j]) >= sim_threshold:
                union(i, j, sim[i, j])

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    kept: list[TestCase] = []
    dedupe_log: list[DedupeEntry] = []
    for members in clusters.values():
        if len(members) == 1:
            kept.append(cases[members[0]])
            continue
        # 选 confidence 最高（等值选最小 index → 稳定）
        members_sorted = sorted(members, key=lambda i: (-cases[i].confidence, i))
        winner_idx = members_sorted[0]
        winner = cases[winner_idx].model_copy(deep=True)
        dropped_ids: list[str] = []
        for m in members_sorted[1:]:
            dropped_ids.append(cases[m].case_id)
            _merge_source_refs(winner, cases[m])
        # similarity 取这个 cluster 里的最大 pair 相似度
        cluster_pairs = [
            v for (a, b), v in pair_sim.items()
            if a in members and b in members
        ]
        sim_repr = max(cluster_pairs) if cluster_pairs else 1.0
        kept.append(winner)
        dedupe_log.append(DedupeEntry(
            kept=winner.case_id,
            dropped=dropped_ids,
            similarity=round(float(sim_repr), 4),
        ))
    # 保持原始输入相对顺序（按每个 cluster 的最小 index 排）
    order = {}
    for members in clusters.values():
        order[min(members)] = members
    kept_ordered: list[TestCase] = []
    for i in sorted(order.keys()):
        members = order[i]
        # 对应 kept 里已处理过的那条
        if len(members) == 1:
            kept_ordered.append(cases[members[0]])
        else:
            # 重新找 winner
            winner_idx = sorted(members, key=lambda x: (-cases[x].confidence, x))[0]
            # kept 里一定能找到该 case_id
            for c in kept:
                if c.case_id == cases[winner_idx].case_id:
                    kept_ordered.append(c)
                    break
    return kept_ordered, dedupe_log


def _merge_source_refs(winner: TestCase, loser: TestCase) -> None:
    """把 loser 的 source_refs 合并进 winner，按 (kp_id, chunk_id, file, section) 去重。"""
    seen: set[tuple] = set()
    for r in winner.source_refs:
        seen.add((r.kp_id, r.chunk_id, r.file, r.section))
    for r in loser.source_refs:
        key = (r.kp_id, r.chunk_id, r.file, r.section)
        if key in seen:
            continue
        seen.add(key)
        winner.source_refs.append(SourceRef(**r.model_dump()))


# ============ 集成用例校验 ===================================================

def _validate_integration_case(
    c: TestCase,
    valid_fp_ids: set[str],
    allowed_kp_ids: set[str],
    allowed_chunk_ids: set[str],
) -> Optional[str]:
    """返回丢弃原因；None 表示用例合法。"""
    rfps = set(c.related_feature_points)
    if len(rfps) < 2:
        return f"related_feature_points 必须 ≥2，实际 {len(rfps)}"
    unknown = rfps - valid_fp_ids
    if unknown:
        return f"related_feature_points 中存在未知 fp_id: {unknown}"
    for ref in c.source_refs:
        kp_ok = bool(ref.kp_id) and ref.kp_id in allowed_kp_ids
        ch_ok = bool(ref.chunk_id) and ref.chunk_id in allowed_chunk_ids
        if not (kp_ok or ch_ok):
            return f"source_ref 不在合法清单: kp_id={ref.kp_id} chunk_id={ref.chunk_id}"
    return None


# ============ Prompt 拼装 ====================================================

def _build_merger_user_prompt(
    feature_points: list[FeaturePoint],
    existing_cases: list[TestCase],
    allowed_kp_ids: set[str],
) -> str:
    fp_lines = [f"  {fp.fp_id}\t{fp.name}\t{fp.module}" for fp in feature_points]
    case_lines = [
        f"  {c.case_id}\t{c.title}\t{c.category}\t{c.feature_point}"
        for c in existing_cases
    ]
    # 控制 kp 列表体积，超过 60 条只展示前 60 + 省略
    kp_list = sorted(allowed_kp_ids)
    if len(kp_list) > 60:
        kp_repr = ", ".join(kp_list[:60]) + f", ...({len(kp_list)-60} more)"
    else:
        kp_repr = ", ".join(kp_list)

    parts = [
        "feature_points (fp_id, name, module):",
        *fp_lines,
        "",
        "cases_summary (case_id, title, category, feature_point):",
        *case_lines,
        "",
        f"kp_dict_keys: {kp_repr}",
        "",
        "请识别跨 ≥2 个 FP 的集成测试场景，严格按 Schema 输出；无需补充则返回空列表。",
    ]
    return "\n".join(parts)
