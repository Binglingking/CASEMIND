"""列同义词映射纯函数测试。"""
from __future__ import annotations

from backend.core.legacy.column_mapper import (
    auto_map,
    header_fingerprint,
    needs_ai_assist,
)


def test_auto_map_exact_synonyms():
    headers = ["用例目录", "模块", "子项", "用例名称",
               "前置条件", "用例步骤", "预期结果",
               "用例类型", "用例等级", "创建人"]
    m = auto_map(headers)
    assert m.hit_ratio == 1.0
    assert m.unmapped_headers == []
    for h in headers:
        assert m.header_to_standard[h] == h


def test_auto_map_english_aliases():
    headers = ["Folder", "Module", "SubModule", "Title",
               "Pre", "Steps", "Expected", "Type", "Priority", "Author"]
    m = auto_map(headers)
    assert m.hit_ratio == 1.0
    assert m.header_to_standard["Folder"] == "用例目录"
    assert m.header_to_standard["Steps"] == "用例步骤"
    assert m.header_to_standard["Priority"] == "用例等级"


def test_auto_map_partial_unknown_columns():
    headers = ["用例名称", "步骤", "预期", "未知列A", "未知列B"]
    m = auto_map(headers)
    assert m.header_to_standard["用例名称"] == "用例名称"
    assert m.header_to_standard["步骤"] == "用例步骤"
    assert m.header_to_standard["预期"] == "预期结果"
    assert m.header_to_standard["未知列A"] == ""
    assert m.header_to_standard["未知列B"] == ""
    assert "未知列A" in m.unmapped_headers
    assert needs_ai_assist(m), "命中率不足应该提示 AI 兜底"


def test_auto_map_extra_synonyms():
    extra = {"用例名称": ["case_summary", "概述"]}
    headers = ["case_summary", "Steps", "Expected"]
    m = auto_map(headers, extra_synonyms=extra)
    assert m.header_to_standard["case_summary"] == "用例名称"
    assert m.header_to_standard["Steps"] == "用例步骤"


def test_header_fingerprint_stable_under_reorder():
    a = ["用例名称", "用例步骤", "预期结果"]
    b = ["预期结果", "用例名称", "用例步骤"]
    assert header_fingerprint(a) == header_fingerprint(b)


def test_header_fingerprint_changes_with_content():
    a = header_fingerprint(["用例名称", "用例步骤"])
    b = header_fingerprint(["用例名称", "用例步骤", "预期结果"])
    assert a != b
