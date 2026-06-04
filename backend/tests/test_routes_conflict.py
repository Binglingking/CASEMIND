"""PR6.3：/api/conflict/* 路由测试。

策略与 test_routes_case_gen 一致：TestClient 直连 FastAPI，桩掉 embed/LLM。
重点验证 feature-flag guard、detect happy、list、resolve、delete、clear。
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agents import conflict_detector as det_mod
from backend.api import routes_conflict
from backend.core import conflict_store, kp_store
from backend.schemas.conflict import ConflictPair
from backend.schemas.knowledge_point import KnowledgePoint, KPSource


PROJECT = "demo"


# ---- 工厂 ------------------------------------------------------------------

def _kp(kp_id: str, content: str = "内容", *,
        module: str = "登录", ktype: str = "business_rule",
        chunk_id: str | None = None) -> KnowledgePoint:
    return KnowledgePoint(
        kp_id=kp_id, type=ktype, content=content, module=module,
        source=KPSource(file=f"{kp_id}.md",
                        chunk_id=chunk_id or f"{kp_id}.md::0::x"),
        doc_version="v1", extracted_at="2026-01-01T00:00:00Z",
    )


def _llm_body() -> dict:
    return {"base_url": "https://x/v1", "api_key": "k", "model": "m"}


# ---- fixtures --------------------------------------------------------------

@pytest.fixture
def enable_flag(tmp_settings):
    from backend import config as cfg_mod
    cfg_mod.FEATURES_STORE_PATH.write_text(
        json.dumps({"enable_conflict_detection": True}), encoding="utf-8",
    )


@pytest.fixture
def client(tmp_settings, enable_flag):
    app = FastAPI()
    app.include_router(routes_conflict.router, prefix="/api/conflict")
    return TestClient(app)


@pytest.fixture
def stub_embed(monkeypatch):
    def fake(texts):
        out = []
        for t in texts:
            digest = hashlib.sha256(t.encode("utf-8")).digest()
            v = np.frombuffer(digest, dtype=np.uint8).astype("float32")
            out.append(v)
        arr = np.array(out, dtype="float32")
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms
    monkeypatch.setattr(det_mod._emb_mod, "embed", fake)


@pytest.fixture
def llm_yes(monkeypatch):
    """LLM 判所有候选均冲突。"""
    def chat(messages, cfg, **kw):
        n = messages[1]["content"].count("--- 第 ")
        items = [{
            "is_conflict": True, "type": "numeric",
            "severity": "high", "description": "数值冲突", "evidence": "A vs B",
        } for _ in range(max(n, 1))]
        return json.dumps({"items": items}, ensure_ascii=False)
    monkeypatch.setattr(det_mod._llm_mod, "chat", chat)


# ---- guard ----------------------------------------------------------------

def test_guard_blocks_when_flag_off(tmp_settings):
    app = FastAPI()
    app.include_router(routes_conflict.router, prefix="/api/conflict")
    c = TestClient(app)
    r = c.get(f"/api/conflict/{PROJECT}")
    assert r.status_code == 403
    assert "enable_conflict_detection" in r.json()["detail"]


# ---- detect ---------------------------------------------------------------

def test_detect_creates_conflict(client, stub_embed, llm_yes):
    kp_store.save_all(PROJECT, [
        _kp("KP_登录_br_0001", "最多重试 5 次", chunk_id="a.md::0::x"),
        _kp("KP_登录_br_0002", "最多重试 10 次", chunk_id="b.md::0::y"),
    ])
    r = client.post(f"/api/conflict/{PROJECT}/detect",
                    json={"llm": _llm_body(), "sim_low": 0.0, "sim_high": 1.0})
    assert r.status_code == 200
    data = r.json()
    assert data["stats"]["new_conflicts"] == 1
    assert len(data["new_conflicts"]) == 1
    assert data["new_conflicts"][0]["type"] == "numeric"


def test_detect_bad_sim_range_400(client):
    r = client.post(f"/api/conflict/{PROJECT}/detect",
                    json={"llm": _llm_body(), "sim_low": 0.9, "sim_high": 0.5})
    assert r.status_code == 400


def test_detect_bad_sim_value_422(client):
    r = client.post(f"/api/conflict/{PROJECT}/detect",
                    json={"llm": _llm_body(), "sim_low": 1.5})
    assert r.status_code == 422


# ---- list -----------------------------------------------------------------

def test_list_empty(client):
    r = client.get(f"/api/conflict/{PROJECT}")
    assert r.status_code == 200
    assert r.json() == {"project": PROJECT, "conflicts": []}


def test_list_after_detect(client, stub_embed, llm_yes):
    kp_store.save_all(PROJECT, [
        _kp("KP_登录_br_0001", "A", chunk_id="a.md::0::x"),
        _kp("KP_登录_br_0002", "B", chunk_id="b.md::0::y"),
    ])
    client.post(f"/api/conflict/{PROJECT}/detect",
                json={"llm": _llm_body(), "sim_low": 0.0, "sim_high": 1.0})
    r = client.get(f"/api/conflict/{PROJECT}")
    assert r.status_code == 200
    assert len(r.json()["conflicts"]) == 1


# ---- resolve --------------------------------------------------------------

def test_resolve_updates_resolution(client, stub_embed, llm_yes):
    kp_store.save_all(PROJECT, [
        _kp("KP_登录_br_0001", "A", chunk_id="a.md::0::x"),
        _kp("KP_登录_br_0002", "B", chunk_id="b.md::0::y"),
    ])
    client.post(f"/api/conflict/{PROJECT}/detect",
                json={"llm": _llm_body(), "sim_low": 0.0, "sim_high": 1.0})
    cid = conflict_store.load_all(PROJECT)[0].conflict_id

    r = client.post(f"/api/conflict/{PROJECT}/{cid}/resolve",
                    json={"resolution": "accept_first", "note": "第一条是准绳"})
    assert r.status_code == 200
    body = r.json()
    assert body["resolution"] == "accept_first"
    assert body["resolved_at"]
    # 持久化验证
    cp = conflict_store.find_by_id(PROJECT, cid)
    assert cp.resolution == "accept_first"


def test_resolve_unknown_id_404(client):
    r = client.post(f"/api/conflict/{PROJECT}/cf_demo_9999/resolve",
                    json={"resolution": "manual"})
    assert r.status_code == 404


def test_resolve_bad_enum_422(client):
    # 先造一条记录（绕过 detect）
    conflict_store.save_all(PROJECT, [ConflictPair(
        conflict_id="cf_demo_0001",
        kp_ids=["KP_A", "KP_B"], type="numeric", severity="high",
        description="x", detected_at="2026-01-01T00:00:00Z",
    )])
    r = client.post(f"/api/conflict/{PROJECT}/cf_demo_0001/resolve",
                    json={"resolution": "invalid_val"})
    assert r.status_code == 422


# ---- delete / clear -------------------------------------------------------

def test_delete_one(client):
    conflict_store.save_all(PROJECT, [ConflictPair(
        conflict_id="cf_demo_0001",
        kp_ids=["KP_A", "KP_B"], type="numeric", severity="high",
        description="x", detected_at="2026-01-01T00:00:00Z",
    )])
    r = client.delete(f"/api/conflict/{PROJECT}/cf_demo_0001")
    assert r.status_code == 200
    assert r.json()["deleted"] == "cf_demo_0001"
    assert conflict_store.load_all(PROJECT) == []


def test_delete_missing_404(client):
    r = client.delete(f"/api/conflict/{PROJECT}/cf_demo_0001")
    assert r.status_code == 404


def test_clear_all(client):
    conflict_store.save_all(PROJECT, [
        ConflictPair(conflict_id="cf_demo_0001", kp_ids=["A", "B"],
                     type="numeric", severity="high",
                     description="x", detected_at="2026-01-01T00:00:00Z"),
        ConflictPair(conflict_id="cf_demo_0002", kp_ids=["C", "D"],
                     type="rule", severity="medium",
                     description="y", detected_at="2026-01-01T00:00:00Z"),
    ])
    r = client.delete(f"/api/conflict/{PROJECT}")
    assert r.status_code == 200
    assert r.json()["cleared"] is True
    assert conflict_store.load_all(PROJECT) == []
