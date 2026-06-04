"""legacy_service.select_legacy_few_shot 测试。

覆盖：
  - 空池返回空
  - module + sub_item_base 命中 → 优先返回
  - 仅 module 命中 → 第二优先级
  - 兜底（任意）
  - LegacyCase → TestCase 字段映射（title 截断 / category 推断 / priority 兜底）
"""
from __future__ import annotations

import pytest

from backend.core.legacy import legacy_store
from backend.schemas.legacy_case import LegacyCase, LegacyCaseFile, LegacyCaseStep
from backend.services import legacy_service


PROJECT = "fewshot_demo"


def _mk_case(case_id: str, *, module="登录", sub="账号-正常流程",
             sub_base="账号", stage="正常流程", title="登录-成功",
             priority="P0", steps=None) -> LegacyCase:
    steps = steps or [LegacyCaseStep(index=1, action="点击登录", expected="跳转首页")]
    return LegacyCase(
        case_id=case_id, module=module, sub_item=sub, sub_item_base=sub_base,
        stage=stage, title=title, priority=priority, steps=steps,
        source_file="t.xlsx", source_row=2,
    )


def _seed(project: str, cases: list[LegacyCase]) -> None:
    meta = LegacyCaseFile(
        file_id="abc12345", name="t.xlsx", ext=".xlsx", size=1, mtime=0.0,
        uploaded_at="2026-01-01T00:00:00Z", case_count=len(cases),
    )
    legacy_store.upsert_case_file(project, meta, cases)


def test_empty_pool_returns_empty(tmp_settings):
    out = legacy_service.select_legacy_few_shot(
        PROJECT, module="登录", sub_item_base="账号", limit=3,
    )
    assert out == []


def test_full_match_priority(tmp_settings):
    cases = [
        _mk_case("LC_a_0001", module="支付", sub_base="下单", stage="异常流程", title="无库存"),
        _mk_case("LC_a_0002", module="登录", sub_base="账号", stage="正常流程", title="成功"),
        _mk_case("LC_a_0003", module="登录", sub_base="账号", stage="异常流程", title="密码错"),
    ]
    _seed(PROJECT, cases)

    out = legacy_service.select_legacy_few_shot(
        PROJECT, module="登录", sub_item_base="账号", stage="正常流程", limit=3,
    )
    # 第 1 优先级应先到位
    assert any(c.case_id == "LC_a_0002" for c in out)
    assert len(out) <= 3


def test_module_only_match_when_no_full(tmp_settings):
    cases = [
        _mk_case("LC_b_0001", module="登录", sub_base="账号", stage="正常流程"),
        _mk_case("LC_b_0002", module="支付", sub_base="下单", stage="正常流程"),
    ]
    _seed(PROJECT, cases)

    out = legacy_service.select_legacy_few_shot(
        PROJECT, module="登录", sub_item_base="完全不存在", limit=3,
    )
    # 应回退到 module-only 命中
    assert len(out) == 1
    assert out[0].case_id == "LC_b_0001"


def test_fallback_any_when_no_module_hit(tmp_settings):
    cases = [_mk_case("LC_c_0001", module="A", sub_base="x")]
    _seed(PROJECT, cases)

    out = legacy_service.select_legacy_few_shot(
        PROJECT, module="不存在", sub_item_base="?", limit=3,
    )
    assert len(out) == 1
    assert out[0].case_id == "LC_c_0001"


def test_priority_normalization(tmp_settings):
    cases = [
        _mk_case("LC_d_0001", priority="高"),
        _mk_case("LC_d_0002", priority=""),
        _mk_case("LC_d_0003", priority="P1"),
    ]
    _seed(PROJECT, cases)

    out = legacy_service.select_legacy_few_shot(
        PROJECT, module="登录", sub_item_base="账号", limit=3,
    )
    pmap = {c.case_id: c.priority for c in out}
    assert pmap["LC_d_0001"] == "P0"   # "高" → P0
    assert pmap["LC_d_0002"] == "P2"   # 空 → P2
    assert pmap["LC_d_0003"] == "P1"


def test_category_inference_from_stage(tmp_settings):
    cases = [
        _mk_case("LC_e_0001", stage="异常流程", title="登录失败"),
        _mk_case("LC_e_0002", stage="正常流程", title="边界值-最大长度"),
        _mk_case("LC_e_0003", stage=None, title="正常登录"),
    ]
    _seed(PROJECT, cases)

    out = legacy_service.select_legacy_few_shot(
        PROJECT, module="登录", sub_item_base="账号", limit=3,
    )
    cmap = {c.case_id: c.category for c in out}
    assert cmap["LC_e_0001"] == "异常"
    assert cmap["LC_e_0002"] == "边界"
    assert cmap["LC_e_0003"] == "正常"


def test_title_truncation_for_oversize(tmp_settings):
    long_title = "测" * 60
    cases = [_mk_case("LC_f_0001", title=long_title)]
    _seed(PROJECT, cases)

    out = legacy_service.select_legacy_few_shot(
        PROJECT, module="登录", sub_item_base="账号", limit=1,
    )
    assert len(out) == 1
    assert len(out[0].title) <= 30


def test_no_steps_synthesizes_placeholder(tmp_settings):
    cases = [_mk_case("LC_g_0001", steps=[])]
    _seed(PROJECT, cases)

    out = legacy_service.select_legacy_few_shot(
        PROJECT, module="登录", sub_item_base="账号", limit=1,
    )
    assert len(out) == 1
    assert len(out[0].steps) >= 1
