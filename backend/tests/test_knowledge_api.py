"""PR2.4：/api/knowledge/* CRUD API 测试。"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import routes_knowledge
from backend.core import kp_store
from backend.schemas.knowledge_point import KnowledgePoint, KPSource


PROJECT = "demo"


def _make_kp(kp_id: str = "KP_登录_br_0001", edited: bool = False,
             module: str = "登录", kp_type: str = "business_rule",
             file: str = "f.md") -> KnowledgePoint:
    return KnowledgePoint(
        kp_id=kp_id, type=kp_type, content="demo",
        module=module,
        source=KPSource(file=file, chunk_id=f"{file}::0::h"),
        doc_version="v1", extracted_at="2026-01-01T00:00:00Z",
        edited_by_user=edited,
    )


@pytest.fixture
def client(tmp_settings):
    app = FastAPI()
    app.include_router(routes_knowledge.router, prefix="/api/knowledge")
    return TestClient(app)


# ---- 列表 / 过滤 ----------------------------------------------------------

def test_list_points_empty(client):
    r = client.get("/api/knowledge/points", params={"project": PROJECT})
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_list_points_returns_saved(client):
    kp_store.save_all(PROJECT, [_make_kp()])
    r = client.get("/api/knowledge/points", params={"project": PROJECT})
    data = r.json()
    assert data["total"] == 1
    assert data["matched"] == 1
    assert data["items"][0]["kp_id"] == "KP_登录_br_0001"


def test_list_filters_by_module(client):
    kp_store.save_all(PROJECT, [
        _make_kp("KP_登录_br_0001", module="登录"),
        _make_kp("KP_下单_br_0001", module="下单"),
    ])
    r = client.get("/api/knowledge/points",
                   params={"project": PROJECT, "module": "登录"})
    assert r.json()["matched"] == 1


def test_list_filters_by_type(client):
    kp_store.save_all(PROJECT, [
        _make_kp("KP_登录_br_0001", kp_type="business_rule"),
        _make_kp("KP_登录_ic_0001", kp_type="input_constraint"),
    ])
    r = client.get("/api/knowledge/points",
                   params={"project": PROJECT, "type": "business_rule"})
    assert r.json()["matched"] == 1


def test_list_keyword_search_matches_content_and_aliases(client):
    kp = _make_kp()
    kp = kp.model_copy(update={"aliases": ["用户认证"], "content": "登录成功跳首页"})
    kp_store.save_all(PROJECT, [kp])
    r = client.get("/api/knowledge/points",
                   params={"project": PROJECT, "q": "用户认证"})
    assert r.json()["matched"] == 1
    r = client.get("/api/knowledge/points",
                   params={"project": PROJECT, "q": "跳首页"})
    assert r.json()["matched"] == 1
    r = client.get("/api/knowledge/points",
                   params={"project": PROJECT, "q": "没有这个词"})
    assert r.json()["matched"] == 0


# ---- stats ---------------------------------------------------------------

def test_stats(client):
    kp_store.save_all(PROJECT, [
        _make_kp("KP_登录_br_0001", module="登录", kp_type="business_rule"),
        _make_kp("KP_登录_ic_0001", module="登录", kp_type="input_constraint", edited=True),
        _make_kp("KP_下单_br_0001", module="下单", kp_type="business_rule"),
    ])
    r = client.get("/api/knowledge/stats", params={"project": PROJECT})
    data = r.json()
    assert data["total"] == 3
    assert data["by_module"] == {"登录": 2, "下单": 1}
    assert data["by_type"] == {"business_rule": 2, "input_constraint": 1}
    assert data["edited_by_user"] == 1


# ---- 编辑 -----------------------------------------------------------------

def test_put_updates_content_and_marks_edited(client):
    kp_store.save_all(PROJECT, [_make_kp()])
    r = client.put(
        "/api/knowledge/points/KP_登录_br_0001",
        params={"project": PROJECT},
        json={"content": "修订后的内容"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["content"] == "修订后的内容"
    assert data["edited_by_user"] is True


def test_put_rejects_empty_body(client):
    kp_store.save_all(PROJECT, [_make_kp()])
    r = client.put(
        "/api/knowledge/points/KP_登录_br_0001",
        params={"project": PROJECT},
        json={},
    )
    assert r.status_code == 400


def test_put_on_missing_id_returns_404(client):
    r = client.put(
        "/api/knowledge/points/KP_不存在",
        params={"project": PROJECT},
        json={"content": "x"},
    )
    assert r.status_code == 404


def test_put_rejects_content_over_max(client):
    kp_store.save_all(PROJECT, [_make_kp()])
    r = client.put(
        "/api/knowledge/points/KP_登录_br_0001",
        params={"project": PROJECT},
        json={"content": "x" * 301},
    )
    assert r.status_code == 422


# ---- 删除 -----------------------------------------------------------------

def test_delete(client):
    kp_store.save_all(PROJECT, [_make_kp()])
    r = client.delete(
        "/api/knowledge/points/KP_登录_br_0001",
        params={"project": PROJECT},
    )
    assert r.status_code == 200
    assert kp_store.load_all(PROJECT) == []


def test_delete_missing_returns_404(client):
    r = client.delete(
        "/api/knowledge/points/KP_missing",
        params={"project": PROJECT},
    )
    assert r.status_code == 404


# ---- 重建 -----------------------------------------------------------------

def test_rebuild_preserves_edited_with_orphan_flag(client):
    kp_store.save_all(PROJECT, [
        _make_kp("KP_登录_br_0001", edited=True),
        _make_kp("KP_登录_br_0002", edited=False),
    ])
    r = client.post("/api/knowledge/rebuild",
                    json={"project": PROJECT, "keep_edited": True})
    assert r.status_code == 200
    assert r.json()["preserved_edited"] == 1
    remaining = kp_store.load_all(PROJECT)
    assert len(remaining) == 1
    assert remaining[0].kp_id == "KP_登录_br_0001"
    assert remaining[0].orphan is True


def test_rebuild_without_keep_edited_clears_all(client):
    kp_store.save_all(PROJECT, [_make_kp(edited=True)])
    r = client.post("/api/knowledge/rebuild",
                    json={"project": PROJECT, "keep_edited": False})
    assert r.status_code == 200
    assert kp_store.load_all(PROJECT) == []
