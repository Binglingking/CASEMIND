"""ConflictDetector — 跨文档需求冲突检测 Agent。

流程（增量友好）：
  1. 载入项目全部 KP，过滤掉 orphan 与低噪类型（api_spec / data_field）。
  2. 按 `module` 分桶（冲突大概率在同模块）；空/未分类 KP 归入 "_none_" 桶单独处理。
  3. 桶内用向量余弦相似度做候选配对：sim ∈ [sim_low, sim_high)。
     - sim_low 太低会冲淡候选（无关配对），默认 0.75。
     - sim_high 过滤"其实是复述"（近乎一字不差），默认 0.99。
  4. 去掉已在 conflict_store 里记录过的 (a,b) 对，避免重复建档。
  5. 把候选对喂给 LLM 批量裁判（单次请求多对），严格 JSON 输出。
  6. is_conflict=True 的对，生成 ConflictPair 并 upsert。

feature flag 检查留给上层（routes_conflict / conflict_service），本 Agent 只做纯逻辑。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from backend.agents.base import load_prompt
from backend.core import conflict_store
from backend.core import embeddings as _emb_mod
from backend.core import kp_store
from backend.core import llm as _llm_mod
from backend.core.llm import LLMConfig, SchemaValidationError, parse_with_schema
from backend.core.timeutil import utc_iso_z
from backend.schemas.conflict import (
    ConflictJudgeOutput,
    ConflictPair,
)
from backend.schemas.knowledge_point import KnowledgePoint


logger = logging.getLogger(__name__)

DETECTOR_VERSION = "v1"

# 进入候选相似度的区间
SIM_LOW_DEFAULT = 0.75
SIM_HIGH_DEFAULT = 0.99

# LLM 一次最多判多少对（控制 token 预算）
JUDGE_BATCH = 12

# 哪些 KP 类型参与冲突检测——其余类型很少出现需求冲突
ELIGIBLE_TYPES = {
    "business_rule", "input_constraint", "boundary",
    "exception_flow", "acceptance_criteria",
}


DEFAULT_JUDGE_SYS = (
    "你是资深需求评审员。用户会给你若干 <A,B> 知识点对，每对来自同一项目的不同文档片段。"
    "请逐一判断它们是否在描述同一事物时相互冲突（数值/枚举/规则/流程/验收标准）。"
    "注意：语义等价或互补都不算冲突；仅当 A 与 B 同时成立会导致测试结论冲突时，才判冲突。"
    "严格按 JSON 返回 {\"items\":[{...}, ...]}，顺序与输入对的顺序一一对应。"
)


# ---- 数据结构 ---------------------------------------------------------------

@dataclass
class DetectStats:
    total_kps: int = 0
    eligible_kps: int = 0
    candidate_pairs: int = 0
    judged_pairs: int = 0
    new_conflicts: int = 0
    skipped_existing: int = 0


@dataclass
class _Candidate:
    a: KnowledgePoint
    b: KnowledgePoint
    sim: float


# ---- 内部辅助 --------------------------------------------------------------

def _now_iso() -> str:
    return utc_iso_z()


def _filter_kps(kps: list[KnowledgePoint]) -> list[KnowledgePoint]:
    return [kp for kp in kps if not kp.orphan and kp.type in ELIGIBLE_TYPES]


def _group_by_module(kps: list[KnowledgePoint]) -> dict[str, list[KnowledgePoint]]:
    buckets: dict[str, list[KnowledgePoint]] = {}
    for kp in kps:
        key = (kp.module or "").strip() or "_none_"
        buckets.setdefault(key, []).append(kp)
    return buckets


def _pairs_from_bucket(
    bucket: list[KnowledgePoint],
    *,
    sim_low: float,
    sim_high: float,
    existing_keys: set[tuple[str, str]],
) -> list[_Candidate]:
    n = len(bucket)
    if n < 2:
        return []
    texts = [kp.content for kp in bucket]
    vecs = _emb_mod.embed(texts)                   # (n, d) 归一化
    sims = vecs @ vecs.T                           # cosine via dot
    out: list[_Candidate] = []
    for i in range(n):
        for j in range(i + 1, n):
            s = float(sims[i, j])
            if s < sim_low or s >= sim_high:
                continue
            a, b = bucket[i], bucket[j]
            # 同一 chunk 里的两条 KP 相似度高是正常现象（拆分不当），也排除
            if a.source.chunk_id == b.source.chunk_id:
                continue
            key = conflict_store.pair_key(a.kp_id, b.kp_id)
            if key in existing_keys:
                continue
            out.append(_Candidate(a=a, b=b, sim=s))
    # 相似度高的优先（更像值得审的冲突）
    out.sort(key=lambda c: -c.sim)
    return out


def _format_judge_prompt(cands: list[_Candidate]) -> str:
    lines = ["请逐对判断是否冲突，items 长度必须等于输入对数。\n\n候选对列表："]
    for i, c in enumerate(cands):
        lines.append(
            f"\n--- 第 {i+1} 对 ---\n"
            f"A. kp_id={c.a.kp_id}  module={c.a.module}  type={c.a.type}\n"
            f"   来源={c.a.source.file}  内容: {c.a.content}\n"
            f"B. kp_id={c.b.kp_id}  module={c.b.module}  type={c.b.type}\n"
            f"   来源={c.b.source.file}  内容: {c.b.content}\n"
        )
    lines.append(
        '\n请返回 JSON：{"items":[{"is_conflict":true/false,'
        '"type":"numeric|enum|rule|flow|acceptance|other",'
        '"severity":"high|medium|low","description":"一句话诊断","evidence":"关键片段"}, ...]}'
    )
    return "\n".join(lines)


def _infer_severity(kp_a: KnowledgePoint, kp_b: KnowledgePoint,
                    llm_severity: str) -> str:
    """LLM 给的 severity 优先；它返回 "" / 不合法值时按类型兜底。"""
    if llm_severity in ("high", "medium", "low"):
        return llm_severity
    high_types = {"business_rule", "acceptance_criteria"}
    if kp_a.type in high_types or kp_b.type in high_types:
        return "high"
    return "medium"


# ---- Agent ----------------------------------------------------------------

class ConflictDetector:
    """线程内同步检测器。单个项目一次调用扫完。"""

    def __init__(self, project: str):
        self.project = project

    def detect(
        self,
        llm_cfg: LLMConfig,
        *,
        sim_low: float = SIM_LOW_DEFAULT,
        sim_high: float = SIM_HIGH_DEFAULT,
        modules: Optional[list[str]] = None,
    ) -> tuple[list[ConflictPair], DetectStats]:
        """运行检测，返回 (本次新增的冲突列表, 统计)。

        - `modules` 若给定，只处理这些模块（其余跳过）。
        - 新增冲突会直接持久化进 conflict_store。
        - 已存在的对直接跳过，不重复判。
        """
        stats = DetectStats()
        kps_all = kp_store.load_all(self.project)
        stats.total_kps = len(kps_all)
        kps = _filter_kps(kps_all)
        if modules:
            mset = set(modules)
            kps = [kp for kp in kps if (kp.module or "") in mset]
        stats.eligible_kps = len(kps)
        if len(kps) < 2:
            return [], stats

        existing_keys = conflict_store.existing_pair_keys(self.project)

        # --- 候选对 ---
        candidates: list[_Candidate] = []
        for mod, bucket in _group_by_module(kps).items():
            cands = _pairs_from_bucket(
                bucket,
                sim_low=sim_low, sim_high=sim_high,
                existing_keys=existing_keys,
            )
            candidates.extend(cands)
        stats.candidate_pairs = len(candidates)
        if not candidates:
            return [], stats

        # --- LLM 裁判（分批） ---
        new_conflicts: list[ConflictPair] = []
        sys_prompt = load_prompt("detect/conflict.txt") or DEFAULT_JUDGE_SYS

        for start in range(0, len(candidates), JUDGE_BATCH):
            batch = candidates[start:start + JUDGE_BATCH]
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": _format_judge_prompt(batch)},
            ]
            try:
                raw = _llm_mod.chat(
                    messages=messages, cfg=llm_cfg,
                    temperature=0.1, json_mode=True,
                )
            except Exception as e:
                logger.warning("conflict judge LLM call failed: %r", e)
                continue

            try:
                parsed: ConflictJudgeOutput = parse_with_schema(
                    raw, ConflictJudgeOutput,
                    retry_cfg=llm_cfg, retry_messages=messages, max_retries=1,
                )
            except SchemaValidationError as e:
                logger.warning("conflict judge schema invalid: %s", e.validation_error)
                continue

            # items 长度期望与 batch 对齐，但 LLM 偶尔不守规——按 min 截取
            stats.judged_pairs += min(len(parsed.items), len(batch))
            for cand, item in zip(batch, parsed.items):
                if not item.is_conflict:
                    continue
                cid = conflict_store.next_conflict_id(self.project)
                cp = ConflictPair(
                    conflict_id=cid,
                    kp_ids=list(conflict_store.pair_key(cand.a.kp_id, cand.b.kp_id)),
                    type=item.type,
                    severity=_infer_severity(cand.a, cand.b, item.severity),
                    module=cand.a.module or cand.b.module,
                    description=item.description or f"{cand.a.kp_id} 与 {cand.b.kp_id} 可能冲突",
                    evidence=item.evidence or None,
                    detected_at=_now_iso(),
                    detector_version=DETECTOR_VERSION,
                    kp_contents=[cand.a.content, cand.b.content],
                )
                # 需要 kp_ids 的顺序与 kp_contents 对齐
                ordered = conflict_store.pair_key(cand.a.kp_id, cand.b.kp_id)
                if ordered[0] == cand.b.kp_id:
                    cp.kp_contents = [cand.b.content, cand.a.content]
                conflict_store.upsert_one(self.project, cp)
                new_conflicts.append(cp)

        stats.new_conflicts = len(new_conflicts)
        stats.skipped_existing = len(existing_keys)
        return new_conflicts, stats
