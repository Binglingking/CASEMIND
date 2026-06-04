"""PR7.3：反馈 few-shot 注入 step2 的测试。

覆盖：
  - enable_feedback_loop off → _build_few_shot_by_fp 返回空 dict，
    且 Generator.run_all 收到 few_shot_by_fp=None（等价旧路径）
  - enable_feedback_loop on + 已有 up-voted 快照 → few_shot_by_fp 注入对应 FP
  - 快照形状不合规 → 静默跳过，不炸裂
"""
from __future__ import annotations

import json

import pytest

from backend.agents.case_gen import pipeline as pipeline_mod
from backend.agents.case_gen.pipeline import _build_few_shot_by_fp
from backend.core import feedback_store
from backend.schemas.feature_point import FeaturePoint
from backend.schemas.feedback import FeedbackRecord


PROJECT = "demo"


def _fp(fp_id: str = "FP_登录_001", module: str = "登录") -> FeaturePoint:
    return FeaturePoint(
        fp_id=fp_id, name=fp_id, description="d", module=module,
        related_kp_ids=["KP_登录_ac_0001"], related_chunk_ids=[],
        priority="P1", user_edited=False,
    )


def _case_snapshot(case_id: str = "TC_登录_0001",
                   fp_id: str = "FP_登录_001",
                   module: str = "登录") -> dict:
    """合法 TestCase 形状的 snapshot。"""
    return {
        "case_id": case_id,
        "title": case_id,
        "priority": "P1",
        "category": "正常",
        "feature_point": fp_id,
        "related_feature_points": [],
        "preconditions": [],
        "steps": [{"step": 1, "action": "操作", "data": "x"}],
        "expected_result": "成功",
        "source_refs": [{"kp_id": "KP_登录_ac_0001", "file": "f.md"}],
        "generated_by": "case_generator_agent",
        "confidence": 0.9,
        "created_at": "2026-04-29T00:00:00Z",
        "needs_review": False,
    }


def _fb(fid: str, *, target_id: str, module: str, snapshot: dict,
        kind: str = "up", created_at: str = "2026-04-29T10:00:00Z") -> FeedbackRecord:
    return FeedbackRecord(
        feedback_id=fid, target_type="case", target_id=target_id,
        pipeline_id="pl_x", module=module, kind=kind,
        snapshot=snapshot, created_at=created_at,
    )


def _set_flag(tmp_settings, value: bool) -> None:
    from backend import config as cfg_mod
    cfg_mod.FEATURES_STORE_PATH.write_text(
        json.dumps({"enable_feedback_loop": value}), encoding="utf-8",
    )


# ---- 直接测 helper ---------------------------------------------------------

def test_build_few_shot_empty_when_flag_off(tmp_settings):
    _set_flag(tmp_settings, False)
    # 即便有快照，flag off 就应该直接返回空
    feedback_store.save_all(PROJECT, [
        _fb("fb_demo_000001", target_id="TC_登录_0001",
            module="登录", snapshot=_case_snapshot()),
    ])
    out = _build_few_shot_by_fp(PROJECT, [_fp()])
    assert out == {}


def test_build_few_shot_picks_module_matched_ups(tmp_settings):
    _set_flag(tmp_settings, True)
    feedback_store.save_all(PROJECT, [
        _fb("fb_demo_000001", target_id="TC_登录_0001",
            module="登录", snapshot=_case_snapshot("TC_登录_0001")),
        # 不同模块——不应被 FP_登录_001 拾取
        _fb("fb_demo_000002", target_id="TC_支付_0001",
            module="支付",
            snapshot=_case_snapshot("TC_支付_0001", module="支付")),
        # down 反馈——过滤掉
        _fb("fb_demo_000003", target_id="TC_登录_0002",
            module="登录", kind="down",
            snapshot=_case_snapshot("TC_登录_0002")),
    ])
    out = _build_few_shot_by_fp(PROJECT, [_fp()])
    assert "FP_登录_001" in out
    cases = out["FP_登录_001"]
    assert len(cases) == 1
    assert cases[0].case_id == "TC_登录_0001"


def test_build_few_shot_skips_invalid_snapshots(tmp_settings):
    _set_flag(tmp_settings, True)
    feedback_store.save_all(PROJECT, [
        # 合法
        _fb("fb_demo_000001", target_id="TC_登录_0001",
            module="登录", snapshot=_case_snapshot("TC_登录_0001")),
        # 只含 case_id/title 的残缺 snapshot —— 不能通过 TestCase.model_validate
        _fb("fb_demo_000002", target_id="TC_登录_0002",
            module="登录",
            snapshot={"case_id": "TC_登录_0002", "title": "登录失败"}),
    ])
    out = _build_few_shot_by_fp(PROJECT, [_fp()])
    assert [c.case_id for c in out["FP_登录_001"]] == ["TC_登录_0001"]


def test_build_few_shot_no_up_feedback_returns_empty(tmp_settings):
    _set_flag(tmp_settings, True)
    out = _build_few_shot_by_fp(PROJECT, [_fp()])
    assert out == {}


# ---- 集成层：确认 pipeline 把 few_shot_by_fp 传给 Generator ---------------

def test_step2_passes_few_shot_to_generator_when_flag_on(
    tmp_settings, monkeypatch,
):
    """step2 跑起来时，Generator.run_all 应收到对应 FP 的 few-shot。"""
    _set_flag(tmp_settings, True)
    feedback_store.save_all(PROJECT, [
        _fb("fb_demo_000001", target_id="TC_登录_0001",
            module="登录", snapshot=_case_snapshot()),
    ])

    captured: dict = {}

    class _FakeGenResult:
        total_cases = 1
        failures: dict = {}
        total_llm_calls = 1

        def to_payload(self) -> dict:
            return {"by_fp": {}, "failures": {},
                    "total_cases": 1, "total_llm_calls": 1}

    class _FakeGenerator:
        def __init__(self, *, project: str) -> None:
            pass

        def run_all(self, fps, kps_index, *,
                    chunks_by_fp=None, few_shot_by_fp=None,
                    llm_cfg=None, max_parallel=4, **_ignored):
            captured["few_shot_by_fp"] = few_shot_by_fp
            captured["fp_ids"] = [fp.fp_id for fp in fps]
            return _FakeGenResult()

    monkeypatch.setattr(pipeline_mod, "Generator", _FakeGenerator)
    monkeypatch.setattr(pipeline_mod.kp_store, "load_all", lambda p: [])

    # 伪造 step1 产物，直接进 step2 入口
    from backend.agents.case_gen import pipeline_io
    from backend.schemas.pipeline_state import PipelineState, LLMConfigSnapshot
    state = pipeline_io.create_state(
        PROJECT, "q",
        llm_cfg=LLMConfigSnapshot(base_url="x", model="m"),
    )
    pipeline_io.write_step_output(state.project, state.pipeline_id, 1, {
        "feature_points": [_fp().model_dump()],
    })
    # 手动把 step1 置为 done 以通过前置校验
    state.steps["step1"].status = "done"
    state.current_step = "step1_done"
    pipeline_io.save_state(state)

    from backend.agents.case_gen.pipeline import CaseGenPipeline
    from backend.core.llm import LLMConfig
    pl = CaseGenPipeline(project=PROJECT)
    out = pl.run_step(state, 2, llm_cfg=LLMConfig("x", "k", "m"))
    assert out.ok
    assert captured["fp_ids"] == ["FP_登录_001"]
    fs = captured["few_shot_by_fp"]
    assert fs is not None and "FP_登录_001" in fs
    assert fs["FP_登录_001"][0].case_id == "TC_登录_0001"


def test_step2_passes_none_when_flag_off(tmp_settings, monkeypatch):
    _set_flag(tmp_settings, False)
    feedback_store.save_all(PROJECT, [
        _fb("fb_demo_000001", target_id="TC_登录_0001",
            module="登录", snapshot=_case_snapshot()),
    ])

    captured: dict = {}

    class _FakeGenResult:
        total_cases = 0
        failures: dict = {}
        total_llm_calls = 0

        def to_payload(self) -> dict:
            return {"by_fp": {}, "failures": {},
                    "total_cases": 0, "total_llm_calls": 0}

    class _FakeGenerator:
        def __init__(self, *, project: str) -> None:
            pass

        def run_all(self, fps, kps_index, *,
                    chunks_by_fp=None, few_shot_by_fp=None,
                    llm_cfg=None, max_parallel=4, **_ignored):
            captured["few_shot_by_fp"] = few_shot_by_fp
            return _FakeGenResult()

    monkeypatch.setattr(pipeline_mod, "Generator", _FakeGenerator)
    monkeypatch.setattr(pipeline_mod.kp_store, "load_all", lambda p: [])

    from backend.agents.case_gen import pipeline_io
    from backend.schemas.pipeline_state import PipelineState, LLMConfigSnapshot
    state = pipeline_io.create_state(
        PROJECT, "q",
        llm_cfg=LLMConfigSnapshot(base_url="x", model="m"),
    )
    pipeline_io.write_step_output(state.project, state.pipeline_id, 1, {
        "feature_points": [_fp().model_dump()],
    })
    state.steps["step1"].status = "done"
    state.current_step = "step1_done"
    pipeline_io.save_state(state)

    from backend.agents.case_gen.pipeline import CaseGenPipeline
    from backend.core.llm import LLMConfig
    pl = CaseGenPipeline(project=PROJECT)
    pl.run_step(state, 2, llm_cfg=LLMConfig("x", "k", "m"))
    # flag off → 我们传 None（不是空 dict）
    assert captured["few_shot_by_fp"] is None
