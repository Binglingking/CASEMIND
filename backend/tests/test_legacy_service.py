"""legacy_service 测试：幂等 ingest + 列映射确认 + warnings 结构化。"""
from __future__ import annotations

import io
import json
import zipfile

import pytest

pd = pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")

from openpyxl import Workbook

from backend.core.legacy import legacy_store
from backend.services import legacy_service


PROJECT = "demo"


def _xlsx_bytes(headers: list[str], rows: list[list[str]], sheet_name: str = "Sheet1") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _full_headers() -> list[str]:
    return ["用例目录", "模块", "子项", "用例名称",
            "前置条件", "用例步骤", "预期结果",
            "用例类型", "用例等级", "创建人"]


def _full_row() -> list[str]:
    return [
        "登录", "账号", "登录-正常流程", "正确账密-登录成功",
        "已注册账号",
        "1. 打开\n2. 输入\n3. 点击",
        "1. 显示\n2. 可输入\n3. 跳转",
        "功能测试", "P0", "alice",
    ]


# ---------- Excel ingest ----------

def test_ingest_excel_happy_path(tmp_settings):
    data = _xlsx_bytes(_full_headers(), [_full_row()])
    res = legacy_service.ingest_excel(PROJECT, "cases.xlsx", data)

    assert res.already_parsed is False
    assert res.needs_user_confirm is False
    assert res.case_count == 1

    files = legacy_store.list_case_files(PROJECT)
    assert len(files) == 1
    assert files[0].file_id == res.file_id

    cases = legacy_store.load_cases(PROJECT, res.file_id)
    assert len(cases) == 1
    assert cases[0].case_id.startswith(f"LC_{res.file_id}_")


def test_ingest_excel_idempotent_same_bytes(tmp_settings):
    data = _xlsx_bytes(_full_headers(), [_full_row()])

    r1 = legacy_service.ingest_excel(PROJECT, "cases.xlsx", data)
    r2 = legacy_service.ingest_excel(PROJECT, "cases.xlsx", data)

    assert r1.file_id == r2.file_id
    assert r1.already_parsed is False
    assert r2.already_parsed is True

    # 不重复落盘
    files = legacy_store.list_case_files(PROJECT)
    assert len(files) == 1


def test_ingest_excel_idempotent_renamed_same_bytes(tmp_settings):
    """不同文件名、同字节也应幂等。"""
    data = _xlsx_bytes(_full_headers(), [_full_row()])
    r1 = legacy_service.ingest_excel(PROJECT, "v1.xlsx", data)
    r2 = legacy_service.ingest_excel(PROJECT, "v2-renamed.xlsx", data)
    assert r1.file_id == r2.file_id
    assert r2.already_parsed is True


def test_ingest_excel_different_bytes_different_id(tmp_settings):
    a = _xlsx_bytes(_full_headers(), [_full_row()])
    row_b = list(_full_row())
    row_b[3] = "另一个标题"
    b = _xlsx_bytes(_full_headers(), [row_b])
    r1 = legacy_service.ingest_excel(PROJECT, "a.xlsx", a)
    r2 = legacy_service.ingest_excel(PROJECT, "b.xlsx", b)
    assert r1.file_id != r2.file_id
    assert len(legacy_store.list_case_files(PROJECT)) == 2


def test_ingest_excel_unknown_columns_request_confirm(tmp_settings):
    """命中率不足 → needs_user_confirm=True，不解析。"""
    weird_headers = ["case_summary", "ops", "results", "Z1", "Z2"]
    rows = [["t", "1. a", "1. b", "x", "y"]]
    data = _xlsx_bytes(weird_headers, rows)

    res = legacy_service.ingest_excel(PROJECT, "weird.xlsx", data)
    assert res.needs_user_confirm is True
    assert res.case_count == 0
    assert res.column_mapping.hit_ratio < 0.9
    # 元数据没写
    assert legacy_store.list_case_files(PROJECT) == []


def test_ingest_excel_with_confirmed_mapping_persists_for_fingerprint(tmp_settings):
    weird_headers = ["case_summary", "ops", "results"]
    rows = [["t1", "1. a", "1. b"]]
    data = _xlsx_bytes(weird_headers, rows)

    from backend.schemas.column_mapping import ColumnMapping

    confirmed = ColumnMapping(
        header_to_standard={
            "case_summary": "用例名称",
            "ops": "用例步骤",
            "results": "预期结果",
        },
        confirmed=True,
        hit_ratio=0.3,
    )
    res = legacy_service.ingest_excel(
        PROJECT, "weird.xlsx", data, confirmed_mapping=confirmed,
    )
    assert res.needs_user_confirm is False
    assert res.case_count == 1

    # 同表头第二份文件（不同字节）应直接复用映射，无需再次确认
    rows2 = [["t2", "1. x", "1. y"]]
    data2 = _xlsx_bytes(weird_headers, rows2)
    res2 = legacy_service.ingest_excel(PROJECT, "weird2.xlsx", data2)
    assert res2.needs_user_confirm is False
    assert res2.case_count == 1


def test_ingest_excel_warnings_structured(tmp_settings):
    """测试步骤和预期结果数量不一致时，不再产生警告。"""
    headers = _full_headers()
    rows = [[
        "登录", "账号", "登录-正常流程", "misaligned",
        "已登录",
        "1. a\n2. b\n3. c", "1. ok",
        "功能测试", "P0", "alice",
    ]]
    data = _xlsx_bytes(headers, rows)

    res = legacy_service.ingest_excel(PROJECT, "w.xlsx", data)
    # 步骤和预期结果数量不一致是正常情况，不再产生警告
    assert not any(w.get("code") == "STEPS_EXPECTED_MISMATCH" for w in res.warnings)
    
    # 验证用例被正确解析，预期结果对齐到最后一步
    cases = legacy_store.load_cases(PROJECT, res.file_id)
    assert len(cases) == 1
    case = cases[0]
    assert len(case.steps) == 3
    # 3个步骤，1个预期，预期应该对齐到第3步
    assert case.steps[0].expected == ""
    assert case.steps[1].expected == ""
    assert case.steps[2].expected == "ok"


# ---------- XMind ingest ----------

def _make_xmind_bytes(root_topic: dict) -> bytes:
    content = [{"id": "s1", "title": "S1", "rootTopic": root_topic}]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("content.json", json.dumps(content, ensure_ascii=False))
        zf.writestr("metadata.json", "{}")
    return buf.getvalue()


def test_ingest_xmind_happy_path(tmp_settings):
    root = {
        "title": "支付", "children": {"attached": [
            {"title": "下单", "children": {"attached": [{"title": "金额>0"}]}},
        ]},
    }
    data = _make_xmind_bytes(root)
    res = legacy_service.ingest_xmind(PROJECT, "p.xmind", data)

    assert res.already_parsed is False
    assert res.node_count >= 3
    assert res.leaf_count == 1


def test_ingest_xmind_idempotent(tmp_settings):
    root = {"title": "A", "children": {"attached": [{"title": "B"}]}}
    data = _make_xmind_bytes(root)
    r1 = legacy_service.ingest_xmind(PROJECT, "x.xmind", data)
    r2 = legacy_service.ingest_xmind(PROJECT, "x.xmind", data)
    assert r1.file_id == r2.file_id
    assert r2.already_parsed is True
    assert len(legacy_store.list_xmind_files(PROJECT)) == 1


def test_ingest_xmind_md(tmp_settings):
    md_data = b"# A\n## B\n### C\n"
    res = legacy_service.ingest_xmind(PROJECT, "x.md", md_data)
    assert res.already_parsed is False
    assert res.node_count >= 4  # 根 + A + B + C


def test_delete_excel_file(tmp_settings):
    data = _xlsx_bytes(_full_headers(), [_full_row()])
    r = legacy_service.ingest_excel(PROJECT, "cases.xlsx", data)
    legacy_service.delete_excel_file(PROJECT, r.file_id)
    assert legacy_store.list_case_files(PROJECT) == []


def test_delete_xmind_file(tmp_settings):
    data = b"# A\n"
    r = legacy_service.ingest_xmind(PROJECT, "a.md", data)
    legacy_service.delete_xmind_file(PROJECT, r.file_id)
    assert legacy_store.list_xmind_files(PROJECT) == []
