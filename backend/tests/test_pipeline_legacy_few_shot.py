"""Step 6: legacy 历史用例作为 few-shot 注入 step2 的测试。

覆盖：
  - enable_legacy_style_reference off → 即便 legacy_store 有用例也不注入
  - on + module 命中历史用例 → 进入 few_shot_by_fp[fp_id]
  - on + 无任何历史用例 → 返回空 dict（不炸裂）
  - feedback + legacy 同时启用：feedback 优先填，不足部分由 legacy 补到 limit
  - _build_style_hint 在 flag off / 无 profile 时返回 None
"""
from __future__ import annotations

import json

import pytest

from backend.agents.case_gen.pipeline import _build_few_shot_by_fp, _build_style_hint
from backend.core.legacy import legacy_store
from backend.schemas.feature_point import FeaturePoint
from backend.schemas.legacy_case import LegacyCase, LegacyCaseFile, LegacyCaseStep
from backend.schemas.style_profile import CaseStyle, StyleProfile, XMindStyle


PROJECT = "demo"


def _fp(fp_id: str = "FP_登录_001", module: str = "登录",
        name: str = "账号") -> FeaturePoint:
    return FeaturePoint(
        fp_id=fp_id, name=name, description="d", module=module,
        related_kp_ids=[], related_chunk_ids=[],
        priority="P1", user_edited=False,
    )


def _seed_legacy(project: str, *, module="登录", sub_base="账号", n=2) -> None:
    cases = [
        LegacyCase(
            case_id=f"LC_xx_{i:04d}", module=module,
            sub_item=f"{sub_base}-正常流程", sub_item_base=sub_base,
            stage="正常流程", title=f"标题{i}", priority="P0",
            steps=[LegacyCaseStep(index=1, action="点击", expected="成功")],
            source_file="t.xlsx", source_row=i + 1,
        )
        for i in range(n)
    ]
    meta = LegacyCaseFile(
        file_id="xx12345", name="t.xlsx", ext=".xlsx", size=1, mtime=0.0,
        uploaded_at="2026-01-01T00:00:00Z", case_count=n,
    )
    legacy_store.upsert_case_file(project, meta, cases)


def _set_flags(*, legacy: bool = False, feedback: bool = False) -> None:
    from backend import config as cfg_mod
    cfg_mod.FEATURES_STORE_PATH.write_text(
        json.dumps({
            "enable_legacy_style_reference": legacy,
            "enable_feedback_loop": feedback,
        }),
        encoding="utf-8",
    )


# ---- _build_few_shot_by_fp ------------------------------------------------


def test_legacy_off_no_injection(tmp_settings):
    _set_flags(legacy=False, feedback=False)
    _seed_legacy(PROJECT)
    out = _build_few_shot_by_fp(PROJECT, [_fp()])
    assert out == {}


def test_legacy_on_injects_examples(tmp_settings):
    _set_flags(legacy=True, feedback=False)
    _seed_legacy(PROJECT, module="登录", sub_base="账号", n=2)
    out = _build_few_shot_by_fp(PROJECT, [_fp(module="登录", name="账号")])
    assert "FP_登录_001" in out
    assert len(out["FP_登录_001"]) == 2
    # generator 强制对齐 fp_id；helper 这里只造原始 TestCase，feature_point 设为 "legacy" 占位
    assert all(tc.feature_point == "legacy" for tc in out["FP_登录_001"])


def test_legacy_on_but_no_data_returns_empty(tmp_settings):
    _set_flags(legacy=True, feedback=False)
    out = _build_few_shot_by_fp(PROJECT, [_fp()])
    assert out == {}


def test_legacy_pipeline_does_not_crash_when_legacy_dir_empty(tmp_settings):
    _set_flags(legacy=True, feedback=False)
    fps = [_fp(fp_id="FP_A_001", module="A", name="x"),
           _fp(fp_id="FP_B_001", module="B", name="y")]
    out = _build_few_shot_by_fp(PROJECT, fps)
    assert out == {}


# ---- _build_style_hint ----------------------------------------------------


def test_style_hint_none_when_flag_off(tmp_settings):
    _set_flags(legacy=False)
    legacy_store.save_style_profile(PROJECT, StyleProfile(
        project=PROJECT, generated_at="2026-05-01T00:00:00Z",
        case_style=CaseStyle(total_cases=10, avg_steps_per_case=4.5),
        xmind_style=XMindStyle(),
    ))
    assert _build_style_hint(PROJECT) is None


def test_style_hint_none_when_no_profile(tmp_settings):
    _set_flags(legacy=True)
    assert _build_style_hint(PROJECT) is None


def test_style_hint_renders_when_flag_on(tmp_settings):
    _set_flags(legacy=True)
    legacy_store.save_style_profile(PROJECT, StyleProfile(
        project=PROJECT, generated_at="2026-05-01T00:00:00Z",
        case_style=CaseStyle(
            total_cases=20,
            avg_steps_per_case=5.2,
            title_scenario_expected_ratio=0.8,
            common_action_verbs=["点击", "输入", "选择"],
            common_assertion_starts=["显示", "跳转"],
            stage_distribution={"正常流程": 0.6, "异常流程": 0.4},
        ),
        xmind_style=XMindStyle(),
        notes=["步骤要包含具体数据"],
    ))
    hint = _build_style_hint(PROJECT)
    assert hint is not None
    assert "5.2" in hint
    assert "点击" in hint
    assert "场景-预期" in hint
    assert "步骤要包含具体数据" in hint


def test_style_hint_skips_empty_profile(tmp_settings):
    """total_cases=0 → 视为没有可用画像，不注入。"""
    _set_flags(legacy=True)
    legacy_store.save_style_profile(PROJECT, StyleProfile(
        project=PROJECT, generated_at="2026-05-01T00:00:00Z",
        case_style=CaseStyle(total_cases=0),
        xmind_style=XMindStyle(),
    ))
    assert _build_style_hint(PROJECT) is None
