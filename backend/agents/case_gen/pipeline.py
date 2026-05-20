"""CaseGenPipeline —— 串联 Slicer → Generator → Merger → Validator 的编排器。

设计约束（docs/design/03 §3）：
  - 每一步独立可重跑 / 可回退；步间通过 `pipeline_state.json` + 各 step 产物 JSON 串联
  - 失败只停在失败那一步；其它步骤的产物保留给 UI diff / debug
  - 编排器本身不负责 UI / 通知；暴露 start / run_step / rollback / apply_user_edit
  - 检索默认使用 HybridRetriever，但允许调用方传入 `retrieved_kps` / `retrieved_chunks`
    以避免首次流水线触发 BGE 重加载（也方便测试注入）
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from backend.agents.base import AgentBase
from backend.agents.case_gen import pipeline_io
from backend.core.timeutil import utc_iso_z
from backend.agents.case_gen.generator import Generator
from backend.agents.case_gen.merger import Merger
from backend.agents.case_gen.pipeline_io import (
    COVERAGE_JSON_FILE,
    COVERAGE_MD_FILE,
    FINAL_CASES_FILE,
    TRACE_FILE,
    mark_user_edited,
    pipeline_dir,
    rollback_to,
    save_state,
    transition_to_done,
    transition_to_failed,
    transition_to_running,
    write_step_output,
)
from backend.agents.case_gen.slicer import Slicer
from backend.agents.case_gen.validator import Validator
from backend.core import kp_store
from backend.core.llm import LLMConfig
from backend.core.vector_store import VectorStore
from backend.schemas.feature_point import FeaturePoint, SliceOutput
from backend.schemas.knowledge_point import KnowledgePoint
from backend.schemas.pipeline_state import LLMConfigSnapshot, PipelineState
from backend.schemas.test_case import TestCase


logger = logging.getLogger(__name__)


# 允许再次触发 step_n 的 status 列表
_RERUNNABLE_STATUSES = {"pending", "done", "failed", "user_edited_pending"}


@dataclass
class StepOutcome:
    """单步运行的返回值。UI 可以直接拿 payload 展示；state 由调用方拿。"""
    step_n: int
    ok: bool
    payload: Optional[dict] = None
    error: Optional[str] = None
    meta: dict = field(default_factory=dict)


class CaseGenPipeline(AgentBase):
    name = "case_gen"

    # ============ 外部入口 ==================================================

    def start(
        self,
        question: str,
        *,
        llm_cfg: LLMConfig,
        mentions: Optional[list[str]] = None,
        filters: Optional[dict] = None,
        pipeline_id: Optional[str] = None,
    ) -> PipelineState:
        """创建新流水线（不跑任何步骤），返回初始 state。"""
        snap = LLMConfigSnapshot(base_url=llm_cfg.base_url, model=llm_cfg.model)
        return pipeline_io.create_state(
            self.project, question,
            llm_cfg=snap, mentions=mentions, filters=filters,
            pipeline_id=pipeline_id,
        )

    def run_step(
        self,
        state: PipelineState,
        step_n: int,
        *,
        llm_cfg: LLMConfig,
        retrieved_kps: Optional[list[KnowledgePoint]] = None,
        retrieved_chunks: Optional[list[dict]] = None,
        chunks_by_fp: Optional[dict[str, list[dict]]] = None,
    ) -> StepOutcome:
        """按编号跑一步。调用方应持有 state 并在成功后继续调用下一步。

        对 step1 可注入 `retrieved_kps`/`retrieved_chunks`；对 step2 可注入
        `chunks_by_fp`。其它情况走默认检索/读盘。
        """
        self._assert_can_run(state, step_n)
        if step_n == 1:
            return self._run_step1(state, llm_cfg=llm_cfg,
                                   retrieved_kps=retrieved_kps,
                                   retrieved_chunks=retrieved_chunks)
        if step_n == 2:
            return self._run_step2(state, llm_cfg=llm_cfg,
                                   chunks_by_fp=chunks_by_fp)
        if step_n == 3:
            return self._run_step3(state, llm_cfg=llm_cfg)
        if step_n == 4:
            return self._run_step4(state, llm_cfg=llm_cfg)
        raise ValueError(f"step must be 1..4, got {step_n}")

    def run_all(
        self,
        state: PipelineState,
        *,
        llm_cfg: LLMConfig,
        retrieved_kps: Optional[list[KnowledgePoint]] = None,
        retrieved_chunks: Optional[list[dict]] = None,
    ) -> list[StepOutcome]:
        """连跑 4 步；任一步失败立即终止。"""
        outcomes: list[StepOutcome] = []
        for n in range(1, 5):
            kw = {}
            if n == 1:
                kw = {"retrieved_kps": retrieved_kps, "retrieved_chunks": retrieved_chunks}
            out = self.run_step(state, n, llm_cfg=llm_cfg, **kw)
            outcomes.append(out)
            if not out.ok:
                break
        return outcomes

    def rollback(self, state: PipelineState, step_n: int) -> PipelineState:
        rollback_to(state, step_n)
        save_state(state)
        return state

    def apply_user_edit(
        self,
        state: PipelineState,
        step_n: int,
        payload: dict,
    ) -> PipelineState:
        """用户在 UI 改了 stepN 的产物 → 持久化 + 标记 stepN+1.. pending。"""
        write_step_output(state.project, state.pipeline_id, step_n, payload)
        mark_user_edited(state, step_n)
        save_state(state)
        return state

    # ============ step 实现（每步独立落盘 + 状态切换） =====================

    def _run_step1(
        self,
        state: PipelineState,
        *,
        llm_cfg: LLMConfig,
        retrieved_kps: Optional[list[KnowledgePoint]],
        retrieved_chunks: Optional[list[dict]],
    ) -> StepOutcome:
        transition_to_running(state, 1)
        save_state(state)

        try:
            if retrieved_kps is None or retrieved_chunks is None:
                r_kps, r_chunks = self._retrieve_for_slicer(state)
                retrieved_kps = retrieved_kps if retrieved_kps is not None else r_kps
                retrieved_chunks = retrieved_chunks if retrieved_chunks is not None else r_chunks

            slicer = Slicer(project=self.project)
            result = slicer.run(
                state.question, retrieved_kps, retrieved_chunks,
                llm_cfg=llm_cfg,
            )
        except Exception as e:
            logger.exception("[pipeline] step1 未预期异常")
            return self._mark_failed(state, 1, f"unexpected: {e!r}")

        if result.error or result.slice_output is None:
            return self._mark_failed(state, 1, result.error or "slicer 返回空")

        payload = {
            "feature_points": [fp.model_dump() for fp in result.slice_output.feature_points],
            "coverage_self_check": result.slice_output.coverage_self_check.model_dump(),
            "retrieved_kp_ids": [kp.kp_id for kp in retrieved_kps],
            "retrieved_chunk_ids": [c.get("chunk_id") for c in retrieved_chunks if c.get("chunk_id")],
            "uncovered_critical": list(result.uncovered_critical),
            "slicer_meta": {
                "llm_calls": result.llm_calls,
                "retries": result.retries,
            },
        }
        return self._mark_done(state, 1, payload)

    def _run_step2(
        self,
        state: PipelineState,
        *,
        llm_cfg: LLMConfig,
        chunks_by_fp: Optional[dict[str, list[dict]]] = None,
    ) -> StepOutcome:
        transition_to_running(state, 2)
        save_state(state)

        step1 = pipeline_io.read_step_output(state.project, state.pipeline_id, 1)
        if not step1:
            return self._mark_failed(state, 2, "step1 产物缺失")

        try:
            fps = [FeaturePoint.model_validate(d) for d in step1.get("feature_points", [])]
        except Exception as e:  # noqa: BLE001
            return self._mark_failed(state, 2, f"step1 feature_points 解析失败: {e!r}")

        kps_index = {kp.kp_id: kp for kp in kp_store.load_all(state.project)}

        few_shot_by_fp = _build_few_shot_by_fp(state.project, fps)
        style_hint = _build_style_hint(state.project)

        try:
            generator = Generator(project=self.project)
            gen_result = generator.run_all(
                fps, kps_index,
                chunks_by_fp=chunks_by_fp,
                few_shot_by_fp=few_shot_by_fp or None,
                llm_cfg=llm_cfg,
                max_parallel=state.context_budget.step2_max_parallel,
                style_hint=style_hint,
            )
        except Exception as e:
            logger.exception("[pipeline] step2 未预期异常")
            return self._mark_failed(state, 2, f"unexpected: {e!r}")

        payload = gen_result.to_payload()
        # 全部 FP 都失败才算 step2 失败；部分失败只写到 failures
        if gen_result.total_cases == 0 and gen_result.failures:
            err = next(iter(gen_result.failures.values()))
            write_step_output(state.project, state.pipeline_id, 2, payload)
            return self._mark_failed(state, 2, f"所有 FP 生成失败；首个错误：{err}")
        return self._mark_done(state, 2, payload)

    def _run_step3(
        self,
        state: PipelineState,
        *,
        llm_cfg: LLMConfig,
        skip_integration: bool = False,
    ) -> StepOutcome:
        transition_to_running(state, 3)
        save_state(state)

        step1 = pipeline_io.read_step_output(state.project, state.pipeline_id, 1)
        step2 = pipeline_io.read_step_output(state.project, state.pipeline_id, 2)
        if not step1 or not step2:
            return self._mark_failed(state, 3, "step1 或 step2 产物缺失")

        try:
            fps = [FeaturePoint.model_validate(d) for d in step1.get("feature_points", [])]
            all_cases: list[TestCase] = []
            for _fp_id, block in (step2.get("by_fp") or {}).items():
                for c in block.get("cases") or []:
                    all_cases.append(TestCase.model_validate(c))
        except Exception as e:  # noqa: BLE001
            return self._mark_failed(state, 3, f"step3 输入解析失败: {e!r}")

        allowed_kp_ids = {kp.kp_id for kp in kp_store.load_all(state.project)}
        allowed_chunk_ids = _all_chunk_ids(state.project)

        try:
            merger = Merger(project=self.project)
            m_result = merger.run(
                cases=all_cases,
                feature_points=fps,
                allowed_kp_ids=allowed_kp_ids,
                allowed_chunk_ids=allowed_chunk_ids,
                llm_cfg=llm_cfg,
                skip_integration=skip_integration,
            )
        except Exception as e:
            logger.exception("[pipeline] step3 未预期异常")
            return self._mark_failed(state, 3, f"unexpected: {e!r}")

        payload = {
            "merged_cases": [c.model_dump() for c in m_result.merged.merged_cases],
            "dedupe_log": [d.model_dump() for d in m_result.merged.dedupe_log],
            "integration_added": list(m_result.merged.integration_added),
            "dedupe_skipped": m_result.dedupe_skipped,
            "integration_skipped": m_result.integration_skipped,
            "llm_calls": m_result.llm_calls,
            "integration_raw_count": m_result.integration_raw_count,
            "integration_filtered": list(m_result.integration_filtered),
            "error": m_result.error,
        }
        return self._mark_done(state, 3, payload)

    def _run_step4(
        self,
        state: PipelineState,
        *,
        llm_cfg: LLMConfig,
    ) -> StepOutcome:
        transition_to_running(state, 4)
        save_state(state)

        step1 = pipeline_io.read_step_output(state.project, state.pipeline_id, 1)
        step3 = pipeline_io.read_step_output(state.project, state.pipeline_id, 3)
        if not step3:
            return self._mark_failed(state, 4, "step3 产物缺失")

        try:
            merged_cases = step3.get("merged_cases") or []
        except Exception as e:  # noqa: BLE001
            return self._mark_failed(state, 4, f"step4 输入解析失败: {e!r}")

        valid_fp_ids: Optional[set[str]] = None
        if step1:
            try:
                valid_fp_ids = {fp["fp_id"] for fp in step1.get("feature_points", [])}
            except Exception:
                valid_fp_ids = None

        allowed_kp_ids = {kp.kp_id for kp in kp_store.load_all(state.project)}
        allowed_chunk_ids = _all_chunk_ids(state.project)

        try:
            validator = Validator(project=self.project)
            v_result = validator.run(
                cases=merged_cases,
                allowed_kp_ids=allowed_kp_ids,
                allowed_chunk_ids=allowed_chunk_ids,
                valid_fp_ids=valid_fp_ids,
            )
        except Exception as e:
            logger.exception("[pipeline] step4 未预期异常")
            return self._mark_failed(state, 4, f"unexpected: {e!r}")

        payload = {
            "valid_cases": [c.model_dump() for c in v_result.output.valid_cases],
            "invalid_cases": [ic.model_dump() for ic in v_result.output.invalid_cases],
            "warnings": list(v_result.output.warnings),
        }

        # 落盘 cases.json + generation_trace.json（最终产物）
        d = pipeline_dir(state.project, state.pipeline_id)
        pipeline_io._atomic_write_json(
            d / FINAL_CASES_FILE, {"cases": payload["valid_cases"]},
        )
        pipeline_io._atomic_write_json(
            d / TRACE_FILE, _build_trace(state),
        )
        return self._mark_done(state, 4, payload)

    # ============ 辅助 =====================================================

    def _assert_can_run(self, state: PipelineState, step_n: int) -> None:
        if step_n not in (1, 2, 3, 4):
            raise ValueError(f"invalid step: {step_n}")
        cur_status = state.steps[f"step{step_n}"].status
        if cur_status == "running":
            raise RuntimeError(
                f"step{step_n} 正在运行中（status={cur_status}），禁止并发触发"
            )
        if cur_status not in _RERUNNABLE_STATUSES:
            raise RuntimeError(
                f"step{step_n} 当前状态不允许运行: {cur_status}"
            )
        # 前置步骤必须 done 或 user_edited_pending
        for prev in range(1, step_n):
            prev_s = state.steps[f"step{prev}"].status
            if prev_s not in ("done", "user_edited_pending"):
                raise RuntimeError(
                    f"前置 step{prev} 未完成（status={prev_s}），无法运行 step{step_n}"
                )

    def _mark_done(
        self,
        state: PipelineState,
        step_n: int,
        payload: dict,
    ) -> StepOutcome:
        write_step_output(state.project, state.pipeline_id, step_n, payload)
        rel_file = pipeline_io.step_output_path(
            state.project, state.pipeline_id, step_n,
        ).name
        transition_to_done(state, step_n, rel_file)
        save_state(state)
        return StepOutcome(step_n=step_n, ok=True, payload=payload)

    def _mark_failed(
        self,
        state: PipelineState,
        step_n: int,
        err: str,
    ) -> StepOutcome:
        transition_to_failed(state, step_n, err)
        save_state(state)
        return StepOutcome(step_n=step_n, ok=False, error=err)

    # ---- 检索默认实现 ----

    def _retrieve_for_slicer(
        self,
        state: PipelineState,
    ) -> tuple[list[KnowledgePoint], list[dict]]:
        """为 Slicer 准备 (kps, chunks)。默认实现：加载全量 KP（按 filters 过滤）+
        用 HybridRetriever 取 top-k chunks。

        生产环境可以覆写此方法走真实检索；测试可直接注入 retrieved_kps / retrieved_chunks。
        """
        # KP：按 filters.module 过滤；截断到 retrieval_top_k_kps
        all_kps = kp_store.load_all(state.project)
        mod = (state.filters or {}).get("module")
        if mod:
            all_kps = [kp for kp in all_kps if kp.module == mod]
        kps = all_kps[: state.context_budget.retrieval_top_k_kps]

        # Chunks：hybrid 检索；失败时返回空列表，不让 step1 崩
        chunks: list[dict] = []
        try:
            from backend.core.hybrid_retriever import HybridRetriever
            use_rr = False
            try:
                from backend.api.routes_settings import get_runtime_features
                use_rr = bool(get_runtime_features().enable_reranker)
            except Exception:
                use_rr = False
            hits = HybridRetriever(state.project).search(
                state.question,
                top_k=state.context_budget.retrieval_top_k_chunks,
                namespace="chunks",
                mode="hybrid",
                filters=state.filters or None,
                use_reranker=use_rr,
            )
            chunks = [
                {
                    "chunk_id": h.chunk.id,
                    "source": h.chunk.source,
                    "text": h.chunk.text,
                }
                for h in hits
            ]
        except Exception as e:
            logger.warning("[pipeline] HybridRetriever 失败，使用空 chunks: %r", e)
        return kps, chunks


# ============ 独立辅助 ======================================================

def _build_few_shot_by_fp(
    project: str,
    fps: list[FeaturePoint],
) -> dict[str, list[TestCase]]:
    """聚合 few-shot 示例：feedback up-voted 快照 + legacy 历史用例。

    - 两路均为开关控制；都关 → 返回空 dict
    - 任意一路失败不影响另一路；最多取 3 条/FP（feedback 优先，legacy 补足）
    - snapshot/LegacyCase 形状不合规跳过该条，不污染 prompt
    """
    LIMIT = 3
    out: dict[str, list[TestCase]] = {}

    try:
        from backend.api.routes_settings import get_runtime_features
        feats = get_runtime_features()
    except Exception as e:  # noqa: BLE001
        logger.warning("[pipeline] features 读取失败（跳过 few-shot）: %r", e)
        return out

    use_feedback = bool(feats.enable_feedback_loop)
    use_legacy = bool(getattr(feats, "enable_legacy_style_reference", False))
    if not use_feedback and not use_legacy:
        return out

    feedback_service = None
    legacy_service = None
    if use_feedback:
        try:
            from backend.services import feedback_service as _fbs
            feedback_service = _fbs
        except Exception as e:  # noqa: BLE001
            logger.warning("[pipeline] feedback_service 不可用: %r", e)
    if use_legacy:
        try:
            from backend.services import legacy_service as _lgs
            legacy_service = _lgs
        except Exception as e:  # noqa: BLE001
            logger.warning("[pipeline] legacy_service 不可用: %r", e)

    for fp in fps:
        examples: list[TestCase] = []

        if feedback_service is not None:
            try:
                snaps = feedback_service.select_positive_examples(
                    project, module=fp.module, limit=LIMIT,
                )
                for snap in snaps or []:
                    try:
                        examples.append(TestCase.model_validate(snap))
                    except Exception:
                        continue
            except Exception as e:  # noqa: BLE001
                logger.warning("[pipeline] select_positive_examples 失败 module=%s: %r",
                               fp.module, e)

        if legacy_service is not None and len(examples) < LIMIT:
            try:
                # FP 没有 sub_item_base/stage；用 fp.name 作为 sub_item_base 模糊匹配
                legacy_cases = legacy_service.select_legacy_few_shot(
                    project,
                    module=fp.module,
                    sub_item_base=fp.name,
                    stage=None,
                    limit=LIMIT - len(examples),
                )
                examples.extend(legacy_cases)
            except Exception as e:  # noqa: BLE001
                logger.warning("[pipeline] select_legacy_few_shot 失败 fp=%s: %r",
                               fp.fp_id, e)

        if examples:
            out[fp.fp_id] = examples[:LIMIT]
    return out


def _build_style_hint(project: str) -> Optional[str]:
    """从 legacy/style_profile.json 构造给 Generator 的风格约束 prompt。

    flag off / 文件缺失 / 解析失败 → 返回 None（保持 prompt 不变）。
    返回字符串只挑对生成有指导意义的几条指标 + notes 前 5 条。
    """
    try:
        from backend.api.routes_settings import get_runtime_features
        if not getattr(get_runtime_features(), "enable_legacy_style_reference", False):
            return None
        from backend.core.legacy import legacy_store
        prof = legacy_store.load_style_profile(project)
        if prof is None or prof.case_style.total_cases == 0:
            return None
    except Exception as e:  # noqa: BLE001
        logger.warning("[pipeline] 加载 style_profile 失败（跳过）: %r", e)
        return None

    cs = prof.case_style
    lines: list[str] = []
    if cs.avg_steps_per_case > 0:
        lines.append(f"- 步骤数：贴近团队均值 {cs.avg_steps_per_case:.1f} 步/用例（允许 ±2）")
    if cs.title_scenario_expected_ratio >= 0.5:
        lines.append("- 标题：优先采用「场景-预期结果」格式（与团队历史 ≥50% 一致）")
    if cs.common_action_verbs:
        verbs = "、".join(cs.common_action_verbs[:8])
        lines.append(f"- 步骤动词：优先选用 {verbs}")
    if cs.common_assertion_starts:
        starts = "、".join(cs.common_assertion_starts[:6])
        lines.append(f"- 预期表达：可用首词 {starts}")
    if cs.stage_distribution:
        top_stages = sorted(cs.stage_distribution.items(), key=lambda x: -x[1])[:3]
        stages_txt = "、".join(f"{k}({v:.0%})" for k, v in top_stages)
        lines.append(f"- 阶段分布参考：{stages_txt}")
    if prof.notes:
        for n in prof.notes[:5]:
            lines.append(f"- {n}")

    return "\n".join(lines) if lines else None


def _all_chunk_ids(project: str) -> set[str]:
    """读出 chunks namespace 里的全部 chunk_id，供 validator / merger 校验。"""
    try:
        vs = VectorStore(project, namespace="chunks")
        return {c.id for c in vs.all_chunks()}
    except Exception as e:  # noqa: BLE001
        logger.warning("[pipeline] 读取 VectorStore 失败: %r", e)
        return set()


def _build_trace(state: PipelineState) -> dict:
    """汇总各步的运行指标到 generation_trace.json。"""
    return {
        "pipeline_id": state.pipeline_id,
        "project": state.project,
        "question": state.question,
        "created_at": state.created_at,
        "updated_at": state.updated_at,
        "current_step": state.current_step,
        "trace_written_at": utc_iso_z(),
        "steps": {
            k: {
                "status": v.status,
                "llm_calls": v.llm_calls,
                "duration_ms": v.duration_ms,
                "error": v.error,
                "user_edited": v.user_edited,
                "output_file": v.output_file,
            }
            for k, v in state.steps.items()
        },
    }
