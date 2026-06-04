"""/api/legacy/* 路由测试。

只覆盖 routes_legacy 自身的薄层逻辑（参数透传 / HTTP 状态码 /
分析触发），核心解析与五阶段细节由对应单元测试负责。
"""
from __future__ import annotations

import io
import json

import openpyxl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import routes_legacy
from backend.core.legacy import legacy_store
from backend.core.timeutil import utc_iso_z
from backend.schemas.legacy_case import LegacyCase, LegacyCaseFile, LegacyCaseStep
from backend.schemas.legacy_xmind import LegacyXMindNode, LegacyXMindTree


PROJECT = "demo"


@pytest.fixture
def client(tmp_settings):
    app = FastAPI()
    app.include_router(routes_legacy.router, prefix="/api/legacy")
    return TestClient(app)


# ---------- 工具：构造一份合法 Excel 字节 ----------

def _make_excel_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    headers = [
        "用例目录", "模块", "子项", "用例名称", "前置条件",
        "用例步骤", "预期结果", "用例类型", "用例等级", "创建人",
    ]
    ws.append(headers)
    ws.append([
        "登录", "账号", "登录-正常流程", "正确账密-登录成功", "已注册",
        "1.打开登录页\n2.输入账密\n3.点击登录",
        "1.登录页可见\n2.输入框可输入\n3.跳转首页",
        "功能测试", "P0", "alice",
    ])
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _seed_case_file():
    case = LegacyCase(
        case_id="LC_seed_0002", suite="登录", module="账号",
        sub_item="登录-正常流程", sub_item_base="登录", stage="正常流程",
        title="正确账密-登录成功", preconditions="已注册",
        steps=[LegacyCaseStep(index=1, action="点击登录", expected="跳转首页")],
        case_type="功能测试", priority="P0", creator="alice",
        source_file="cases.xlsx", source_row=2,
    )
    legacy_store.upsert_case_file(
        PROJECT,
        LegacyCaseFile(
            file_id="seed", name="cases.xlsx", ext=".xlsx",
            size=10, mtime=1.0, uploaded_at=utc_iso_z(),
            case_count=1, sheet_names=["Sheet1"],
        ),
        [case],
    )


def _seed_xmind():
    legacy_store.upsert_xmind_tree(
        PROJECT,
        LegacyXMindTree(
            file_id="xseed", name="t.xmind", ext=".xmind",
            size=10, mtime=1.0, uploaded_at=utc_iso_z(),
            root_id="r",
            nodes=[
                LegacyXMindNode(node_id="r", title="支付", depth=0, path=["支付"],
                                parent_id=None, children_ids=["a"], is_leaf=False),
                LegacyXMindNode(node_id="a", title="金额>0", depth=1, path=["支付", "金额>0"],
                                parent_id="r", children_ids=[], is_leaf=True),
            ],
        ),
    )


# ---------- 历史用例 ----------

def test_list_case_files_empty(client):
    r = client.get("/api/legacy/cases", params={"project": PROJECT})
    assert r.status_code == 200
    assert r.json() == {"project": PROJECT, "files": []}


def test_peek_excel_headers(client):
    content = _make_excel_bytes()
    r = client.post(
        "/api/legacy/cases/peek-headers",
        data={"project": PROJECT},
        files={"file": ("cases.xlsx", content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sheet_names"] == ["Sheet1"]
    assert "用例名称" in body["headers"]


def test_upload_case_excel_and_idempotent(client):
    content = _make_excel_bytes()
    files = {"file": ("cases.xlsx", content,
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

    r1 = client.post("/api/legacy/cases/upload",
                     data={"project": PROJECT}, files=files)
    assert r1.status_code == 200
    body = r1.json()
    assert body["ok"] is True
    assert body["already_parsed"] is False
    assert body["case_count"] == 1
    fid = body["file_id"]

    # 重传相同字节 → already_parsed=True
    r2 = client.post("/api/legacy/cases/upload",
                     data={"project": PROJECT},
                     files={"file": ("cases.xlsx", content,
                                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r2.status_code == 200
    assert r2.json()["already_parsed"] is True
    assert r2.json()["file_id"] == fid


def test_get_case_file_404(client):
    r = client.get(f"/api/legacy/cases/no_such", params={"project": PROJECT})
    assert r.status_code == 404


def test_delete_case_file(client, tmp_settings):
    _seed_case_file()
    r = client.delete(f"/api/legacy/cases/seed", params={"project": PROJECT})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert legacy_store.list_case_files(PROJECT) == []


# ---------- 历史 XMind ----------

def test_list_xmind_empty(client):
    r = client.get("/api/legacy/xmind", params={"project": PROJECT})
    assert r.status_code == 200
    assert r.json()["files"] == []


def test_get_xmind_404(client):
    r = client.get("/api/legacy/xmind/no_such", params={"project": PROJECT})
    assert r.status_code == 404


def test_delete_xmind(client, tmp_settings):
    _seed_xmind()
    r = client.delete("/api/legacy/xmind/xseed", params={"project": PROJECT})
    assert r.status_code == 200
    assert legacy_store.list_xmind_files(PROJECT) == []


# ---------- 列映射 ----------

def test_column_mapping_get_default(client):
    r = client.get("/api/legacy/column-mapping", params={"project": PROJECT})
    assert r.status_code == 200
    assert "by_fingerprint" in r.json()


def test_column_mapping_confirm(client):
    body = {
        "project": PROJECT,
        "fingerprint": "fp_xxx",
        "mapping": {
            "header_to_standard": {"用例名称": "title"},
            "unmapped_headers": [],
            "confirmed": False,
            "hit_ratio": 1.0,
        },
    }
    r = client.post("/api/legacy/column-mapping/confirm", json=body)
    assert r.status_code == 200
    saved = legacy_store.load_column_mapping_store(PROJECT)
    assert "fp_xxx" in saved.by_fingerprint
    assert saved.by_fingerprint["fp_xxx"].confirmed is True


# ---------- 风格画像 ----------

def test_style_empty(client):
    r = client.get("/api/legacy/style", params={"project": PROJECT})
    assert r.status_code == 200
    assert r.json() == {"project": PROJECT, "profile": None}


# ---------- 反哺候选 ----------

def test_inferred_list_empty(client):
    r = client.get("/api/legacy/inferred", params={"project": PROJECT})
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_inferred_review_404(client):
    r = client.post("/api/legacy/inferred/review", json={
        "project": PROJECT, "inferred_id": "no_such", "decision": "accept",
    })
    assert r.status_code == 400


def test_inferred_review_invalid_decision(client):
    r = client.post("/api/legacy/inferred/review", json={
        "project": PROJECT, "inferred_id": "x", "decision": "maybe",
    })
    assert r.status_code == 400


# ---------- 五阶段分析 ----------

def test_analyze_skip_extract(client, tmp_settings):
    _seed_case_file()
    _seed_xmind()
    r = client.post("/api/legacy/analyze", json={
        "project": PROJECT,
        "llm": {"base_url": "x", "api_key": "x", "model": "x"},
        "skip_extract": True,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["llm_calls"] == 0
    assert body["case_units_count"] == 1
    profile = legacy_store.load_style_profile(PROJECT)
    assert profile is not None
