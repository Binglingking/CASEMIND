"""PR4.5：Step 4 Validator Agent 测试。

要点：
  - 全部为代码校验，不触发 LLM / embedding
  - 覆盖 Schema 失败、追溯断链、case_id 重复/命名、集成 FP 数量、抽象 data warning
  - 空输入 / 全合法 / 四类覆盖自检
"""
from __future__ import annotations

import pytest

from backend.agents.case_gen.validator import Validator
from backend.schemas.test_case import CaseStep, SourceRef, TestCase


PROJECT = "demo"


def _case(case_id: str = "TC_登录_0001",
          fp_id: str = "FP_登录_001",
          category: str = "正常",
          kp: str = "KP_登录_br_0001",
          chunk_id: str | None = None,
          related_fps: list[str] | None = None,
          generated_by: str = "case_generator_agent",
          data: str = "13800138000") -> TestCase:
    return TestCase(
        case_id=case_id,
        title=case_id,
        priority="P1",
        category=category,
        feature_point=fp_id,
        related_feature_points=list(related_fps or []),
        preconditions=[],
        steps=[CaseStep(step=1, action="输入手机号", data=data)],
        expected_result="成功",
        source_refs=[SourceRef(kp_id=kp, chunk_id=chunk_id, file="f.md")],
        generated_by=generated_by,
        confidence=0.9,
        created_at="2026-04-29T00:00:00Z",
        needs_review=False,
    )


# ---- happy path ---------------------------------------------------------

def test_all_valid(tmp_settings):
    c1 = _case("TC_登录_0001")
    c2 = _case("TC_登录_0002", category="异常", data="000")
    c3 = _case("TC_登录_0003", category="边界", data="a"*21)
    c4 = _case("TC_登录_0004", category="安全", data="admin' OR 1=1--")
    agent = Validator(project=PROJECT)
    res = agent.run(
        cases=[c1, c2, c3, c4],
        allowed_kp_ids={"KP_登录_br_0001"},
        allowed_chunk_ids=set(),
    )
    assert res.valid_count == 4
    assert res.invalid_count == 0
    assert res.output.warnings == []


# ---- Schema 失败 --------------------------------------------------------

def test_schema_failure_goes_to_invalid(tmp_settings):
    # title 超过 30 字；pydantic 会拒
    bad = {
        "case_id": "TC_登录_0001",
        "title": "这个标题故意写得很长很长很长很长很长很长很长很长很长很长超过三十个字",
        "priority": "P1",
        "category": "正常",
        "feature_point": "FP_登录_001",
        "related_feature_points": [],
        "preconditions": [],
        "steps": [{"step": 1, "action": "x", "data": "y"}],
        "expected_result": "ok",
        "source_refs": [{"kp_id": "KP_x", "file": "f.md"}],
        "generated_by": "case_generator_agent",
        "confidence": 0.9,
        "created_at": "2026-04-29T00:00:00Z",
        "needs_review": False,
    }
    agent = Validator(project=PROJECT)
    res = agent.run(
        cases=[bad],
        allowed_kp_ids={"KP_x"},
        allowed_chunk_ids=set(),
    )
    assert res.valid_count == 0
    assert res.invalid_count == 1
    assert any("title" in e for e in res.output.invalid_cases[0].errors)


# ---- source_refs 追溯断链 ----------------------------------------------

def test_source_ref_not_in_allowed(tmp_settings):
    c = _case(kp="KP_不存在")
    agent = Validator(project=PROJECT)
    res = agent.run(
        cases=[c],
        allowed_kp_ids={"KP_其他"},
        allowed_chunk_ids=set(),
    )
    assert res.valid_count == 0
    assert res.invalid_count == 1
    assert any("追溯断链" in e for e in res.output.invalid_cases[0].errors)


def test_source_ref_chunk_id_ok(tmp_settings):
    """kp_id 缺失但 chunk_id 合法 → 仍然 valid。"""
    c = TestCase(
        case_id="TC_登录_0001",
        title="x", priority="P1", category="正常",
        feature_point="FP_登录_001",
        preconditions=[],
        steps=[CaseStep(step=1, action="x", data="y")],
        expected_result="ok",
        source_refs=[SourceRef(chunk_id="a.md::0::h", file="a.md")],
        created_at="2026-04-29T00:00:00Z",
    )
    agent = Validator(project=PROJECT)
    res = agent.run(
        cases=[c],
        allowed_kp_ids=set(),
        allowed_chunk_ids={"a.md::0::h"},
    )
    assert res.valid_count == 1


# ---- case_id 相关 -------------------------------------------------------

def test_case_id_duplicate(tmp_settings):
    c1 = _case("TC_登录_0001")
    c2 = _case("TC_登录_0001", category="异常")
    agent = Validator(project=PROJECT)
    res = agent.run(
        cases=[c1, c2],
        allowed_kp_ids={"KP_登录_br_0001"},
        allowed_chunk_ids=set(),
    )
    assert res.valid_count == 1
    assert res.invalid_count == 1
    assert any("重复" in e for e in res.output.invalid_cases[0].errors)


def test_case_id_naming_invalid(tmp_settings):
    c = _case("BAD_NAME_01")
    agent = Validator(project=PROJECT)
    res = agent.run(
        cases=[c],
        allowed_kp_ids={"KP_登录_br_0001"},
        allowed_chunk_ids=set(),
    )
    assert res.valid_count == 0
    assert any("命名不合规" in e for e in res.output.invalid_cases[0].errors)


# ---- 集成用例 ----------------------------------------------------------

def test_integration_case_must_have_two_related_fps(tmp_settings):
    c = _case(
        "TC_集成_0001",
        generated_by="merger_agent",
        related_fps=["FP_登录_001"],   # 只有 1 个
    )
    agent = Validator(project=PROJECT)
    res = agent.run(
        cases=[c],
        allowed_kp_ids={"KP_登录_br_0001"},
        allowed_chunk_ids=set(),
        valid_fp_ids={"FP_登录_001"},
    )
    assert res.valid_count == 0
    assert any("≥2" in e for e in res.output.invalid_cases[0].errors)


def test_related_fp_unknown(tmp_settings):
    c = _case(
        "TC_集成_0001",
        generated_by="merger_agent",
        related_fps=["FP_登录_001", "FP_幻想_999"],
    )
    agent = Validator(project=PROJECT)
    res = agent.run(
        cases=[c],
        allowed_kp_ids={"KP_登录_br_0001"},
        allowed_chunk_ids=set(),
        valid_fp_ids={"FP_登录_001"},
    )
    assert res.valid_count == 0
    assert any("未知 fp_id" in e for e in res.output.invalid_cases[0].errors)


def test_related_fp_unknown_without_fp_whitelist_ignored(tmp_settings):
    """valid_fp_ids=None → 不做 fp 白名单检查。"""
    c = _case(
        "TC_集成_0001",
        generated_by="merger_agent",
        related_fps=["FP_a", "FP_b"],
    )
    agent = Validator(project=PROJECT)
    res = agent.run(
        cases=[c],
        allowed_kp_ids={"KP_登录_br_0001"},
        allowed_chunk_ids=set(),
        valid_fp_ids=None,
    )
    assert res.valid_count == 1


# ---- 抽象 data 只给 warning --------------------------------------------

def test_abstract_data_produces_warning_not_error(tmp_settings):
    c = _case(data="合法手机号")
    agent = Validator(project=PROJECT)
    res = agent.run(
        cases=[c],
        allowed_kp_ids={"KP_登录_br_0001"},
        allowed_chunk_ids=set(),
    )
    assert res.valid_count == 1
    assert any("抽象描述" in w for w in res.output.warnings)


# ---- 四类覆盖自检 ------------------------------------------------------

def test_missing_category_warning(tmp_settings):
    # 只有正常 + 异常，缺边界/安全
    c1 = _case("TC_登录_0001", category="正常")
    c2 = _case("TC_登录_0002", category="异常")
    agent = Validator(project=PROJECT)
    res = agent.run(
        cases=[c1, c2],
        allowed_kp_ids={"KP_登录_br_0001"},
        allowed_chunk_ids=set(),
    )
    assert res.valid_count == 2
    merged = " ".join(res.output.warnings)
    assert "边界" in merged and "安全" in merged


def test_empty_cases(tmp_settings):
    agent = Validator(project=PROJECT)
    res = agent.run(
        cases=[],
        allowed_kp_ids=set(),
        allowed_chunk_ids=set(),
    )
    assert res.valid_count == 0
    assert res.invalid_count == 0
    assert res.output.warnings == []


# ---- 接受 dict 输入（被用户编辑过的场景） ------------------------------

def test_accepts_dict_inputs(tmp_settings):
    d = {
        "case_id": "TC_登录_0001", "title": "x", "priority": "P1",
        "category": "正常", "feature_point": "FP_登录_001",
        "related_feature_points": [], "preconditions": [],
        "steps": [{"step": 1, "action": "a", "data": "b"}],
        "expected_result": "ok",
        "source_refs": [{"kp_id": "KP_x", "file": "f.md"}],
        "generated_by": "user", "confidence": 1.0,
        "created_at": "2026-04-29T00:00:00Z", "needs_review": False,
    }
    agent = Validator(project=PROJECT)
    res = agent.run(
        cases=[d],
        allowed_kp_ids={"KP_x"},
        allowed_chunk_ids=set(),
    )
    assert res.valid_count == 1
