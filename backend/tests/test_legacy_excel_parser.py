"""历史用例 Excel 解析器测试。

依赖：openpyxl 已在项目运行环境内（运行用例生成 Excel 输出已用）。
不依赖 pandas 测试时若环境不具备会自动跳过。
"""
from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")

from backend.core.legacy.column_mapper import auto_map
from backend.core.legacy.excel_parser import (
    _split_numbered_lines,
    _split_stage,
    parse_excel,
)


def test_split_numbered_lines_basic():
    text = "1. 打开登录页\n2. 输入账号\n3. 输入密码"
    out = _split_numbered_lines(text)
    assert out == ["打开登录页", "输入账号", "输入密码"]


def test_split_numbered_lines_circled():
    text = "①打开页\n②点击按钮"
    out = _split_numbered_lines(text)
    assert out == ["打开页", "点击按钮"]


def test_split_numbered_lines_step_prefix():
    text = "Step1: 启动\nStep 2: 点击"
    out = _split_numbered_lines(text)
    assert out == ["启动", "点击"]


def test_split_numbered_lines_empty():
    assert _split_numbered_lines("") == []
    assert _split_numbered_lines(None) == []


def test_split_stage_chinese_dash():
    base, stage = _split_stage("绑定手机号-前置准备", ["前置准备", "正常流程"])
    assert base == "绑定手机号"
    assert stage == "前置准备"


def test_split_stage_no_suffix():
    base, stage = _split_stage("绑定手机号", ["前置准备"])
    assert base == "绑定手机号"
    assert stage is None


def _make_workbook(path, headers, rows, sheet_name="Sheet1"):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for r in rows:
        ws.append(r)
    wb.save(path)


def test_parse_excel_happy_path(tmp_path):
    headers = ["用例目录", "模块", "子项", "用例名称",
               "前置条件", "用例步骤", "预期结果",
               "用例类型", "用例等级", "创建人"]
    rows = [
        ["登录", "账号", "登录-正常流程", "正确账密-登录成功",
         "已注册账号", "1. 打开登录页\n2. 输入账号密码\n3. 点击登录",
         "1. 登录页可见\n2. 输入框可输入\n3. 跳转首页",
         "功能测试", "P0", "alice"],
    ]
    f = tmp_path / "cases.xlsx"
    _make_workbook(f, headers, rows)

    mapping = auto_map(headers)
    cases, sheets, warnings = parse_excel(f, mapping, file_id="abcd1234")
    assert len(cases) == 1
    c = cases[0]
    assert c.case_id.startswith("LC_abcd1234_")
    assert c.title == "正确账密-登录成功"
    assert c.suite == "登录"
    assert c.module == "账号"
    assert c.sub_item == "登录-正常流程"
    assert c.sub_item_base == "登录"
    assert c.stage == "正常流程"
    assert c.priority == "P0"
    assert len(c.steps) == 3
    assert c.steps[0].action == "打开登录页"
    assert c.steps[0].expected == "登录页可见"
    assert c.steps[2].expected == "跳转首页"
    assert c.source_row == 2
    assert sheets == ["Sheet1"]
    assert warnings == []


def test_parse_excel_steps_expected_misaligned_warns(tmp_path):
    headers = ["用例名称", "用例步骤", "预期结果"]
    rows = [
        ["短预期", "1. 第一步\n2. 第二步\n3. 第三步", "1. 通过"],
    ]
    f = tmp_path / "x.xlsx"
    _make_workbook(f, headers, rows)
    mapping = auto_map(headers)
    cases, _, warnings = parse_excel(f, mapping)
    assert len(cases) == 1
    # 现在应该保留所有步骤，即使数量不匹配
    assert len(cases[0].steps) == 3, "应保留所有步骤和预期结果"
    
    # 验证预期结果对齐到最后一步
    # 3个步骤，1个预期，预期应该对齐到第3步
    assert cases[0].steps[0].action == "第一步"
    assert cases[0].steps[0].expected == ""  # 前两步没有预期
    assert cases[0].steps[1].action == "第二步"
    assert cases[0].steps[1].expected == ""  # 前两步没有预期
    assert cases[0].steps[2].action == "第三步"
    assert cases[0].steps[2].expected == "通过"  # 最后一步有预期
    
    # 不再产生警告
    assert not any(w.code == "STEPS_EXPECTED_MISMATCH" for w in warnings)


def test_parse_excel_unmapped_columns_kept_in_extra(tmp_path):
    headers = ["用例名称", "用例步骤", "预期结果", "备注", "JIRA单号"]
    rows = [
        ["自由列保留", "1. a", "1. b", "迁移单", "ABC-123"],
    ]
    f = tmp_path / "x.xlsx"
    _make_workbook(f, headers, rows)
    mapping = auto_map(headers)
    cases, _, _ = parse_excel(f, mapping)
    assert cases[0].extra.get("备注") == "迁移单"
    assert cases[0].extra.get("JIRA单号") == "ABC-123"


def test_parse_excel_skip_empty_title_rows(tmp_path):
    headers = ["用例名称", "用例步骤", "预期结果"]
    rows = [
        ["", "1. a", "1. b"],
        ["有标题", "1. a", "1. b"],
    ]
    f = tmp_path / "x.xlsx"
    _make_workbook(f, headers, rows)
    mapping = auto_map(headers)
    cases, _, _ = parse_excel(f, mapping)
    assert len(cases) == 1
    assert cases[0].title == "有标题"
    assert cases[0].source_row == 3
