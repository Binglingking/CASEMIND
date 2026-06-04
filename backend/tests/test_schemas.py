"""PR1.2：pydantic schema 冒烟测试。

只校验核心约束（禁写的字段确实禁写、必填确实必填），不做语义测试。
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.schemas import (
    CaseStep,
    CoverageReport,
    FeaturePoint,
    KnowledgePoint,
    KPExtractItem,
    KPSource,
    PipelineState,
    SourceRef,
    TestCase,
)
from backend.schemas.pipeline_state import ContextBudgetSnapshot, LLMConfigSnapshot


# --- KnowledgePoint ----------------------------------------------------------

def test_knowledge_point_happy_path():
    kp = KnowledgePoint(
        kp_id="KP_登录_br_0001",
        type="business_rule",
        content="密码长度 8~20 位",
        module="登录",
        source=KPSource(file="login.md", chunk_id="login.md::3::5", section="3.2"),
        doc_version="2026-04-01",
        extracted_at="2026-04-28T08:00:00Z",
    )
    assert kp.aliases == []
    assert kp.edited_by_user is False
    assert kp.orphan is False


def test_kp_type_must_be_enum():
    with pytest.raises(ValidationError):
        KPExtractItem(type="unknown_type", content="x", module="登录")


def test_kp_content_max_length():
    with pytest.raises(ValidationError):
        KPExtractItem(type="business_rule", content="x" * 301, module="登录")


# --- FeaturePoint ------------------------------------------------------------

def test_feature_point_defaults():
    fp = FeaturePoint(
        fp_id="FP_登录_001",
        name="账号密码登录",
        description="用户输入用户名和密码登录系统",
        module="登录",
    )
    assert fp.priority == "P1"
    assert fp.user_edited is False


# --- TestCase ----------------------------------------------------------------

def test_test_case_source_ref_requires_kp_or_chunk():
    with pytest.raises(ValidationError) as excinfo:
        SourceRef(file="x.md")
    assert "kp_id" in str(excinfo.value) or "chunk_id" in str(excinfo.value)


def test_test_case_needs_steps_and_source_refs():
    with pytest.raises(ValidationError):
        TestCase(
            case_id="TC_登录_0001",
            title="登录成功",
            priority="P0",
            category="正常",
            feature_point="FP_登录_001",
            expected_result="进入首页",
            source_refs=[],   # 空
            steps=[CaseStep(step=1, action="输入用户名")],
            created_at="2026-04-28T00:00:00Z",
        )


def test_test_case_happy_path():
    tc = TestCase(
        case_id="TC_登录_0001",
        title="登录成功",
        priority="P0",
        category="正常",
        feature_point="FP_登录_001",
        expected_result="进入首页",
        steps=[CaseStep(step=1, action="输入合法用户名密码", data="admin/Abc12345")],
        source_refs=[SourceRef(kp_id="KP_登录_br_0001", file="login.md", section="3.2")],
        created_at="2026-04-28T00:00:00Z",
    )
    assert tc.needs_review is False
    assert tc.related_feature_points == []


# --- PipelineState -----------------------------------------------------------

def test_pipeline_state_defaults():
    ps = PipelineState(
        pipeline_id="pl_20260428_160530_a1b2",
        project="演示",
        question="为登录生成用例",
        created_at="2026-04-28T00:00:00Z",
        updated_at="2026-04-28T00:00:00Z",
        llm_cfg_snapshot=LLMConfigSnapshot(base_url="https://x/api/v1", model="m"),
        context_budget=ContextBudgetSnapshot(
            per_call_max_tokens=30000, history_max_chars=12000,
            retrieval_top_k_chunks=8, retrieval_top_k_kps=15,
            step2_max_parallel=4,
        ),
    )
    assert set(ps.steps.keys()) == {"step1", "step2", "step3", "step4"}
    assert all(s.status == "pending" for s in ps.steps.values())
    assert ps.current_step == "step1_pending"


# --- CoverageReport ----------------------------------------------------------

def test_coverage_report_empty():
    r = CoverageReport(
        pipeline_id="pl_x",
        project="p",
        generated_at="2026-04-28T00:00:00Z",
        total_kps=0,
        total_cases=0,
        strict_coverage=0.0,
        weighted_coverage=0.0,
    )
    assert r.uncovered_kps == []
    assert r.by_module == {}
