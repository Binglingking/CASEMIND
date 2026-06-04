"""PR7.2：/api/feedback/* 路由测试。"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import routes_feedback
from backend.core import feedback_store
from backend.schemas.feedback import FeedbackRecord


PROJECT = "demo"


# ---- fixtures --------------------------------------------------------------

@pytest.fixture
def enable_flag(tmp_settings):
    from backend import config as cfg_mod
    cfg_mod.FEATURES_STORE_PATH.write_text(
        json.dumps({"enable_feedback_loop": True}), encoding="utf-8",
    )


@pytest.fixture
def client(tmp_settings, enable_flag):
    app = FastAPI()
    app.include_router(routes_feedback.router, prefix="/api/feedback")
    return TestClient(app)


def _body(**kw) -> dict:
    base = {
        "target_id": "TC_登录_0001",
        "kind": "up",
        "pipeline_id": "pl_20260429_100000_abcd",
        "module": "登录",
        "note": "清晰",
    }
    base.update(kw)
    # snapshot 默认跟随 target_id，测试不再需要单独塞
    base.setdefault("snapshot", {"case_id": base["target_id"], "title": "登录成功"})
    return base


# ---- guard -----------------------------------------------------------------

def test_guard_blocks_when_flag_off(tmp_settings):
    app = FastAPI()
    app.include_router(routes_feedback.router, prefix="/api/feedback")
    c = TestClient(app)
    r = c.get(f"/api/feedback/{PROJECT}")
    assert r.status_code == 403
    assert "enable_feedback_loop" in r.json()["detail"]


# ---- submit ---------------------------------------------------------------

def test_submit_up(client):
    r = client.post(f"/api/feedback/{PROJECT}", json=_body())
    assert r.status_code == 200
    data = r.json()
    assert data["kind"] == "up"
    assert data["feedback_id"].startswith("fb_demo_")
    assert data["created_at"].endswith("Z")


def test_submit_bad_kind_422(client):
    r = client.post(f"/api/feedback/{PROJECT}", json=_body(kind="confused"))
    assert r.status_code == 422


def test_submit_missing_target_422(client):
    body = _body()
    del body["target_id"]
    r = client.post(f"/api/feedback/{PROJECT}", json=body)
    assert r.status_code == 422


# ---- list / filter --------------------------------------------------------

def test_list_and_filter(client):
    client.post(f"/api/feedback/{PROJECT}", json=_body(target_id="TC_A", kind="up"))
    client.post(f"/api/feedback/{PROJECT}", json=_body(target_id="TC_B", kind="down"))
    client.post(f"/api/feedback/{PROJECT}", json=_body(target_id="TC_A", kind="down"))

    r_all = client.get(f"/api/feedback/{PROJECT}")
    assert len(r_all.json()["feedback"]) == 3

    r_up = client.get(f"/api/feedback/{PROJECT}?kind=up")
    assert [f["target_id"] for f in r_up.json()["feedback"]] == ["TC_A"]

    r_tc_a = client.get(f"/api/feedback/{PROJECT}?target_id=TC_A")
    assert len(r_tc_a.json()["feedback"]) == 2


def test_list_bad_kind_422(client):
    r = client.get(f"/api/feedback/{PROJECT}?kind=bogus")
    assert r.status_code == 422


# ---- summary --------------------------------------------------------------

def test_summary_counts(client):
    client.post(f"/api/feedback/{PROJECT}", json=_body(kind="up"))
    client.post(f"/api/feedback/{PROJECT}", json=_body(kind="down"))
    client.post(f"/api/feedback/{PROJECT}",
                json=_body(kind="up", module="支付", target_id="TC_支付_0001"))
    r = client.get(f"/api/feedback/{PROJECT}/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    assert data["by_kind"]["up"] == 2
    assert data["by_kind"]["down"] == 1
    assert data["by_module"]["登录"]["up"] == 1
    assert data["by_module"]["支付"]["up"] == 1


# ---- examples -------------------------------------------------------------

def test_examples_picks_latest_ups(client):
    client.post(f"/api/feedback/{PROJECT}", json=_body(target_id="TC_1", kind="up"))
    client.post(f"/api/feedback/{PROJECT}", json=_body(target_id="TC_2", kind="down"))
    client.post(f"/api/feedback/{PROJECT}",
                json=_body(target_id="TC_3", kind="up", module="支付"))

    r = client.get(f"/api/feedback/{PROJECT}/examples?module=登录&limit=5")
    assert r.status_code == 200
    ids = [x["case_id"] for x in r.json()["examples"]]
    assert ids == ["TC_1"]  # 只模块=登录 + kind=up


def test_examples_limit(client):
    for i in range(5):
        client.post(f"/api/feedback/{PROJECT}",
                    json=_body(target_id=f"TC_{i}", kind="up"))
    r = client.get(f"/api/feedback/{PROJECT}/examples?limit=2")
    assert len(r.json()["examples"]) == 2


def test_examples_bad_limit_422(client):
    r = client.get(f"/api/feedback/{PROJECT}/examples?limit=99")
    assert r.status_code == 422


# ---- delete / clear -------------------------------------------------------

def test_delete_one(client):
    r = client.post(f"/api/feedback/{PROJECT}", json=_body())
    fid = r.json()["feedback_id"]
    r_del = client.delete(f"/api/feedback/{PROJECT}/{fid}")
    assert r_del.status_code == 200
    assert r_del.json()["deleted"] == fid
    assert feedback_store.load_all(PROJECT) == []


def test_delete_missing_404(client):
    r = client.delete(f"/api/feedback/{PROJECT}/fb_demo_999999")
    assert r.status_code == 404


def test_clear_all(client):
    client.post(f"/api/feedback/{PROJECT}", json=_body(target_id="TC_A"))
    client.post(f"/api/feedback/{PROJECT}", json=_body(target_id="TC_B"))
    r = client.delete(f"/api/feedback/{PROJECT}")
    assert r.status_code == 200
    assert r.json()["cleared"] is True
    assert feedback_store.load_all(PROJECT) == []
