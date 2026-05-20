"""Step 2：并行用例生成 Agent（Case Generator）。

职责：对每个 FeaturePoint **独立调用一次 LLM**，产出该 FP 的测试用例集合。

并发模型：`concurrent.futures.ThreadPoolExecutor(max_workers=N)` + 同步 chat()。
不改造为 asyncio——保持与现有 chat() 的单线程阻塞 API 一致。

容错：
  - 任何一个 FP 失败只影响该 FP（记到 errors），不阻断其他 FP
  - Schema 校验失败 / LLM 抛错 / JSON 跑偏都归为"失败"
  - 调用方可以读 `GenerateAllResult.failures` 决定是否要整体重跑或让用户忽略

调用者：CaseGenPipeline.run_step2
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

from backend.agents.base import AgentBase, load_prompt
from backend.core import llm as _llm_mod
from backend.core.llm import LLMConfig, SchemaValidationError, parse_with_schema
from backend.schemas.feature_point import FeaturePoint
from backend.schemas.knowledge_point import KnowledgePoint
from backend.schemas.test_case import GenerateOutput, TestCase


logger = logging.getLogger(__name__)


# 每个 FP 输入 KP 的上限（docs/design/03 §6.5 预算）
MAX_KPS_PER_FP = 15
MAX_CHUNKS_PER_FP = 5
MAX_FEWSHOT_EXAMPLES = 3

DEFAULT_GENERATOR_SYS = (
    "你是测试用例设计专家。为单一功能点生成覆盖完整的测试用例（正常/异常/边界/安全四类）。"
    "每条用例的 source_refs 必须引用输入的 kp_id 或 chunk_id；steps.data 必须具体到值；"
    "只返回合法 JSON。"
)


@dataclass
class FPGenerationResult:
    """单个 FP 的产出。"""
    fp_id: str
    cases: list[TestCase] = field(default_factory=list)
    self_check: Optional[dict] = None
    llm_calls: int = 0
    duration_ms: int = 0
    error: Optional[str] = None


@dataclass
class GenerateAllResult:
    """整个 Step 2 的产出。"""
    results: dict[str, FPGenerationResult] = field(default_factory=dict)
    total_llm_calls: int = 0
    total_cases: int = 0
    failures: dict[str, str] = field(default_factory=dict)       # fp_id -> error

    @property
    def all_cases(self) -> list[TestCase]:
        out: list[TestCase] = []
        for r in self.results.values():
            out.extend(r.cases)
        return out

    def to_payload(self) -> dict:
        """产出 step2_cases_by_fp.json 的完整载荷。"""
        return {
            "by_fp": {
                fp_id: {
                    "cases": [c.model_dump() for c in r.cases],
                    "self_check": r.self_check,
                    "llm_call_meta": {
                        "llm_calls": r.llm_calls,
                        "duration_ms": r.duration_ms,
                    },
                    "error": r.error,
                }
                for fp_id, r in self.results.items()
            },
            "failures": dict(self.failures),
            "total_cases": self.total_cases,
            "total_llm_calls": self.total_llm_calls,
        }


class Generator(AgentBase):
    name = "generator"

    def run_all(
        self,
        feature_points: list[FeaturePoint],
        kps_index: dict[str, KnowledgePoint],
        chunks_by_fp: Optional[dict[str, list[dict]]] = None,
        few_shot_by_fp: Optional[dict[str, list[TestCase]]] = None,
        *,
        llm_cfg: LLMConfig,
        max_parallel: int = 4,
        style_hint: Optional[str] = None,
    ) -> GenerateAllResult:
        """对所有 FP 并行生成用例。

        Parameters
        ----------
        kps_index : dict[str, KnowledgePoint]
            全量 KP 查找表：kp_id -> KnowledgePoint。Generator 会按 fp.related_kp_ids
            取对应 KP 作为输入。
        chunks_by_fp : dict[str, list[dict]], optional
            fp_id -> 补充 chunks。每条 dict 至少含 chunk_id/file/text。
        few_shot_by_fp : dict[str, list[TestCase]], optional
            fp_id -> 历史用例样例（可能为空）。
        """
        out = GenerateAllResult()
        if not feature_points:
            return out

        chunks_by_fp = chunks_by_fp or {}
        few_shot_by_fp = few_shot_by_fp or {}

        def _task(fp: FeaturePoint) -> FPGenerationResult:
            return self._generate_one(
                fp, kps_index=kps_index,
                chunks=chunks_by_fp.get(fp.fp_id, []),
                few_shot=few_shot_by_fp.get(fp.fp_id, []),
                llm_cfg=llm_cfg,
                style_hint=style_hint,
            )

        # max_workers 至少 1，至多 FP 数
        workers = max(1, min(max_parallel, len(feature_points)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_task, fp): fp for fp in feature_points}
            for fut in as_completed(futures):
                fp = futures[fut]
                try:
                    res = fut.result()
                except Exception as e:
                    # ThreadPoolExecutor 抛出的罕见异常（理论上 _generate_one 已兜底）
                    logger.exception("[generator] 未预期异常 fp=%s", fp.fp_id)
                    res = FPGenerationResult(fp_id=fp.fp_id, error=f"unexpected: {e!r}")
                out.results[fp.fp_id] = res
                out.total_llm_calls += res.llm_calls
                out.total_cases += len(res.cases)
                if res.error:
                    out.failures[fp.fp_id] = res.error
        return out

    # ---- 单 FP 生成（一次 LLM 调用 + 一次 retry by parse_with_schema） ----

    def _generate_one(
        self,
        fp: FeaturePoint,
        *,
        kps_index: dict[str, KnowledgePoint],
        chunks: list[dict],
        few_shot: list[TestCase],
        llm_cfg: LLMConfig,
        style_hint: Optional[str] = None,
    ) -> FPGenerationResult:
        import time
        t0 = time.monotonic()
        result = FPGenerationResult(fp_id=fp.fp_id)

        related_kps = [
            kps_index[kid] for kid in fp.related_kp_ids[:MAX_KPS_PER_FP]
            if kid in kps_index
        ]
        trimmed_chunks = chunks[:MAX_CHUNKS_PER_FP]
        trimmed_fewshot = few_shot[:MAX_FEWSHOT_EXAMPLES]

        sys_prompt = load_prompt("case_gen/02_generator.txt") or DEFAULT_GENERATOR_SYS
        if style_hint:
            sys_prompt = f"{sys_prompt}\n\n# 团队风格约束\n{style_hint}"
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": _build_user_prompt(
                fp, related_kps, trimmed_chunks, trimmed_fewshot,
            )},
        ]

        try:
            raw = _llm_mod.chat(
                messages=messages, cfg=llm_cfg,
                temperature=0.2, json_mode=True,
            )
            result.llm_calls += 1
        except Exception as e:
            result.error = f"LLM 调用失败: {e!r}"
            result.duration_ms = int((time.monotonic() - t0) * 1000)
            return result

        try:
            out: GenerateOutput = parse_with_schema(
                raw, GenerateOutput,
                retry_cfg=llm_cfg,
                retry_messages=messages,
                max_retries=1,
            )
        except SchemaValidationError as e:
            result.error = f"Schema 校验失败: {e}"
            result.duration_ms = int((time.monotonic() - t0) * 1000)
            return result

        # 可接受 LLM 生成 feature_point 与输入 fp_id 略有偏差——强制对齐
        allowed_kp_ids = {kp.kp_id for kp in related_kps}
        allowed_chunk_ids = {c.get("chunk_id") for c in trimmed_chunks if c.get("chunk_id")}
        for c in out.cases:
            if c.feature_point != fp.fp_id:
                c.feature_point = fp.fp_id
        result.cases = out.cases
        result.self_check = out.self_check.model_dump()
        # 轻量级后端校验：记录 broken refs 到 self_check 便于 validator 复用
        broken = _count_broken_refs(out.cases, allowed_kp_ids, allowed_chunk_ids)
        if broken:
            result.self_check["broken_refs_count"] = broken
        result.duration_ms = int((time.monotonic() - t0) * 1000)
        return result


# ============ prompt 拼装 ===================================================

def _kp_line(kp: KnowledgePoint) -> str:
    content = (kp.content or "").replace("\n", " ").strip()
    if len(content) > 180:
        content = content[:180] + "..."
    return f"{kp.kp_id}\t{kp.type}\t{content}"


def _chunk_line(c: dict) -> str:
    cid = c.get("chunk_id") or "?"
    txt = (c.get("text") or "").replace("\n", " ").strip()
    if len(txt) > 260:
        txt = txt[:260] + "..."
    return f"{cid}\t{txt}"


def _build_user_prompt(
    fp: FeaturePoint,
    kps: list[KnowledgePoint],
    chunks: list[dict],
    few_shot: list[TestCase],
) -> str:
    parts = [
        "feature_point:",
        f"  fp_id: {fp.fp_id}",
        f"  name: {fp.name}",
        f"  description: {fp.description}",
        f"  module: {fp.module}",
        f"  priority: {fp.priority}",
        "",
        "related_kps (kp_id, type, content):",
    ]
    parts.extend(f"  {_kp_line(kp)}" for kp in kps) if kps else parts.append("  (无)")
    parts.extend(["", "relevant_chunks (chunk_id, text):"])
    if chunks:
        parts.extend(f"  {_chunk_line(c)}" for c in chunks)
    else:
        parts.append("  (无)")
    parts.extend(["", "few_shot_examples:"])
    if few_shot:
        for i, ex in enumerate(few_shot, 1):
            parts.append(f"  示例{i}: title={ex.title}, category={ex.category}, "
                         f"steps_count={len(ex.steps)}")
    else:
        parts.append("  (无)")
    parts.extend([
        "",
        "请为该 feature_point 生成覆盖 正常/异常/边界/安全 四类的测试用例，严格按 Schema 返回 JSON。",
        "每条用例的 source_refs 必须引用 related_kps 的 kp_id 或 relevant_chunks 的 chunk_id。",
    ])
    return "\n".join(parts)


def _count_broken_refs(
    cases: list[TestCase],
    allowed_kp_ids: set[str],
    allowed_chunk_ids: set[str],
) -> int:
    broken = 0
    for c in cases:
        for ref in c.source_refs:
            kp_ok = ref.kp_id in allowed_kp_ids if ref.kp_id else False
            ch_ok = ref.chunk_id in allowed_chunk_ids if ref.chunk_id else False
            if not (kp_ok or ch_ok):
                broken += 1
    return broken
