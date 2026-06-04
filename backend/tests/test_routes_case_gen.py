"""PR4.8：/api/case-gen/* 路由测试。

策略：
  - TestClient 直连 FastAPI，不起 uvicorn
  - 打开 enable_case_gen_pipeline flag（写 features.json）
  - 复用 test_pipeline.py 的 monkeypatch 思路，把 LLM/BGE/VectorStore 全部桩掉
  - 只验证路由行为（状态码、字段形状、state 持久化），不再重复 pipeline 内部逻辑测试
"""
from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agents.case_gen import pipeline as pipeline_mod
from backend.agents.case_gen import slicer as slicer_mod
from backend.agents.case_gen import merger as merger_mod
from backend.api import routes_case_gen, routes_settings
from backend.schemas.knowledge_point import KnowledgePoint, KPSource


PROJECT = "demo"


# ---------- 工厂 ------------------------------------------------------------

def _kp(kp_id: str = "KP_登录_ac_0001",
        ktype: str = "acceptance_criteria") -> KnowledgePoint:
    return KnowledgePoint(
        kp_id=kp_id, type=ktype, content="登录成功后跳转首页",
        module="登录",
        source=KPSource(file="f.md", chunk_id="f.md::0::h"),
        doc_version="v1", extracted_at="2026-01-01T00:00:00Z",
    )


def _slice_raw() -> str:
    return json.dumps({
        "feature_points": [{
            "fp_id": "FP_登录_001",
            "name": "FP_登录_001",
            "description": "desc",
            "module": "登录",
            "related_kp_ids": ["KP_登录_ac_0001"],
            "related_chunk_ids": [],
            "priority": "P1",
            "user_edited": False,
        }],
        "coverage_self_check": {
            "total_kps_input": 1,
            "kps_covered_by_feature_points": 1,
            "uncovered_kp_ids": [],
        },
    }, ensure_ascii=False)


def _case_dict() -> dict:
    return {
        "case_id": "TC_登录_0001",
        "title": "登录成功",
        "priority": "P1",
        "category": "正常",
        "feature_point": "FP_登录_001",
        "related_feature_points": [],
        "preconditions": [],
        "steps": [{"step": 1, "action": "登录", "data": "x"}],
        "expected_result": "成功",
        "source_refs": [{"kp_id": "KP_登录_ac_0001", "file": "f.md", "section": None}],
        "generated_by": "case_generator_agent",
        "confidence": 0.9,
        "created_at": "2026-04-29T00:00:00Z",
        "needs_review": False,
    }


def _gen_raw() -> str:
    return json.dumps({
        "cases": [_case_dict()],
        "self_check": {
            "normal_count": 1, "exception_count": 0,
            "boundary_count": 0, "security_count": 0,
            "all_source_refs_valid": True,
        },
    }, ensure_ascii=False)


class _StubVS:
    def __init__(self, *a, **kw):
        pass

    def all_chunks(self):
        return []


# ---------- fixtures ---------------------------------------------------------

@pytest.fixture
def enable_pipeline(tmp_settings):
    """把 enable_case_gen_pipeline 开关写到磁盘上。"""
    from backend import config as cfg_mod
    cfg_mod.FEATURES_STORE_PATH.write_text(
        json.dumps({"enable_case_gen_pipeline": True}), encoding="utf-8",
    )


@pytest.fixture
def client(tmp_settings, enable_pipeline):
    app = FastAPI()
    # case-gen 的 guard 会去读 features.json，所以 settings router 不是必需
    app.include_router(routes_case_gen.router, prefix="/api/case-gen")
    return TestClient(app)


@pytest.fixture
def wire(monkeypatch):
    """与 test_pipeline.py 同款：dispatch_chat 按 system prompt 路由三种 agent。"""
    state = {
        "slice_raw": _slice_raw(),
        "gen_raw": _gen_raw(),
        "merger_raw": json.dumps({"integration_cases": [], "rationale": "none"}),
        "kps": [_kp()],
    }

    monkeypatch.setattr(pipeline_mod.kp_store, "load_all",
                        lambda project: list(state["kps"]))
    monkeypatch.setattr(pipeline_mod, "VectorStore", _StubVS)

    def dispatch_chat(messages, cfg, **kw):
        sys_text = messages[0]["content"] if messages else ""
        if "测试需求分析专家" in sys_text or "SliceOutput" in sys_text:
            return state["slice_raw"]
        if "测试架构师" in sys_text or "integration_cases" in sys_text:
            return state["merger_raw"]
        return state["gen_raw"]

    monkeypatch.setattr(slicer_mod._llm_mod, "chat", dispatch_chat)

    def fake_embed(texts):
        import hashlib
        out = []
        for t in texts:
            h = int(hashlib.md5(t.encode("utf-8")).hexdigest(), 16)
            v = np.zeros(8, dtype="float32")
            v[h % 8] = 1.0
            out.append(v)
        arr = np.array(out, dtype="float32")
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms
    monkeypatch.setattr(merger_mod._emb_mod, "embed", fake_embed)

    return state


def _llm_body():
    return {"base_url": "https://x/v1", "api_key": "k", "model": "m"}


# ---------- 开关 guard ------------------------------------------------------

def test_guard_blocks_when_flag_off(tmp_settings):
    app = FastAPI()
    app.include_router(routes_case_gen.router, prefix="/api/case-gen")
    c = TestClient(app)
    r = c.post("/api/case-gen/start", json={
        "project": PROJECT, "question": "登录", "llm": _llm_body(),
    })
    assert r.status_code == 403
    assert "enable_case_gen_pipeline" in r.json()["detail"]


# ---------- 主流程 ----------------------------------------------------------

def test_start_creates_pipeline(client, wire):
    r = client.post("/api/case-gen/start", json={
        "project": PROJECT, "question": "登录功能", "llm": _llm_body(),
    })
    assert r.status_code == 200
    data = r.json()
    assert data["project"] == PROJECT
    assert data["question"] == "登录功能"
    assert data["current_step"] == "step1_pending"
    assert data["pipeline_id"].startswith("pl_")


def test_list_pipelines(client, wire):
    client.post("/api/case-gen/start", json={
        "project": PROJECT, "question": "q1", "llm": _llm_body(),
    })
    client.post("/api/case-gen/start", json={
        "project": PROJECT, "question": "q2", "llm": _llm_body(),
    })
    r = client.get("/api/case-gen/list", params={"project": PROJECT})
    assert r.status_code == 200
    pids = [p["pipeline_id"] for p in r.json()["pipelines"]]
    assert len(pids) == 2
    # 升序（id 内含时间）
    assert pids == sorted(pids)


def test_get_pipeline_returns_state_and_outputs(client, wire):
    start = client.post("/api/case-gen/start", json={
        "project": PROJECT, "question": "登录", "llm": _llm_body(),
    }).json()
    pid = start["pipeline_id"]

    r = client.get(f"/api/case-gen/{PROJECT}/{pid}")
    assert r.status_code == 200
    body = r.json()
    assert body["state"]["pipeline_id"] == pid
    # 未跑任何 step，产物全空
    assert body["step_outputs"] == {"1": None, "2": None, "3": None, "4": None}


def test_get_pipeline_404(client, wire):
    r = client.get(f"/api/case-gen/{PROJECT}/pl_20260101_000000_abcd")
    assert r.status_code == 404


def test_run_step1_happy(client, wire):
    pid = client.post("/api/case-gen/start", json={
        "project": PROJECT, "question": "登录", "llm": _llm_body(),
    }).json()["pipeline_id"]

    r = client.post(f"/api/case-gen/{PROJECT}/{pid}/step/1/run",
                    json={"llm": _llm_body()})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["step_n"] == 1
    assert body["state"]["current_step"] == "step1_done"
    assert body["payload"]["feature_points"][0]["fp_id"] == "FP_登录_001"


def test_run_step_prereq_rejected_409(client, wire):
    pid = client.post("/api/case-gen/start", json={
        "project": PROJECT, "question": "登录", "llm": _llm_body(),
    }).json()["pipeline_id"]
    # 直接跑 step2 → pipeline 内部 _assert_can_run 抛 RuntimeError → 409
    r = client.post(f"/api/case-gen/{PROJECT}/{pid}/step/2/run",
                    json={"llm": _llm_body()})
    assert r.status_code == 409


def test_run_step_invalid_number_400(client, wire):
    pid = client.post("/api/case-gen/start", json={
        "project": PROJECT, "question": "登录", "llm": _llm_body(),
    }).json()["pipeline_id"]
    r = client.post(f"/api/case-gen/{PROJECT}/{pid}/step/9/run",
                    json={"llm": _llm_body()})
    assert r.status_code == 400


def test_user_edit_invalidates_later(client, wire):
    pid = client.post("/api/case-gen/start", json={
        "project": PROJECT, "question": "登录", "llm": _llm_body(),
    }).json()["pipeline_id"]
    # 先跑 step1 + step2
    client.post(f"/api/case-gen/{PROJECT}/{pid}/step/1/run", json={"llm": _llm_body()})
    client.post(f"/api/case-gen/{PROJECT}/{pid}/step/2/run", json={"llm": _llm_body()})

    # 用户改 step1 产物
    edited = {"feature_points": [], "coverage_self_check": {
        "total_kps_input": 0, "kps_covered_by_feature_points": 0, "uncovered_kp_ids": []},
        "user_note": "manual"}
    r = client.put(f"/api/case-gen/{PROJECT}/{pid}/step/1/output",
                   json={"payload": edited})
    assert r.status_code == 200
    state = r.json()
    assert state["steps"]["step1"]["user_edited"] is True
    assert state["steps"]["step2"]["status"] == "pending"


def test_rollback_resets_later_steps(client, wire):
    pid = client.post("/api/case-gen/start", json={
        "project": PROJECT, "question": "登录", "llm": _llm_body(),
    }).json()["pipeline_id"]
    client.post(f"/api/case-gen/{PROJECT}/{pid}/step/1/run", json={"llm": _llm_body()})
    client.post(f"/api/case-gen/{PROJECT}/{pid}/step/2/run", json={"llm": _llm_body()})

    r = client.post(f"/api/case-gen/{PROJECT}/{pid}/rollback", json={"step_n": 2})
    assert r.status_code == 200
    state = r.json()
    assert state["current_step"] == "step2_pending"
    assert state["steps"]["step2"]["status"] == "pending"


def test_rollback_invalid_step_422(client, wire):
    pid = client.post("/api/case-gen/start", json={
        "project": PROJECT, "question": "登录", "llm": _llm_body(),
    }).json()["pipeline_id"]
    # pydantic 校验 ge=1/le=4 → 422
    r = client.post(f"/api/case-gen/{PROJECT}/{pid}/rollback", json={"step_n": 0})
    assert r.status_code == 422
