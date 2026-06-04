"""PR4.8：/api/coverage/* 路由测试。

策略：
  - 不跑真流水线，手工在 pipeline 目录里造 cases.json + pipeline_state.json
  - monkey-patch coverage._emb_mod.embed 避免加载 BGE
  - 验证 compute / summary / cached read / feature-flag guard
"""
from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agents.case_gen import pipeline_io
from backend.analytics import coverage as cov_mod
from backend.api import routes_coverage
from backend.core import kp_store
from backend.schemas.knowledge_point import KnowledgePoint, KPSource
from backend.schemas.pipeline_state import (
    ContextBudgetSnapshot, LLMConfigSnapshot, PipelineState, StepState,
)


PROJECT = "demo"
PIPELINE_ID = "pl_20260101_120000_abcd"


# ---------- 工厂 ------------------------------------------------------------

def _kp(kp_id: str = "KP_1") -> KnowledgePoint:
    return KnowledgePoint(
        kp_id=kp_id, type="business_rule", content="rule",
        module="登录",
        source=KPSource(file="a.md", chunk_id="a.md::0::h"),
        doc_version="v1", extracted_at="2026-01-01T00:00:00Z",
    )


def _case_dict(kp_ref: str = "KP_1") -> dict:
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
        "source_refs": [{"kp_id": kp_ref, "file": "a.md"}],
        "generated_by": "case_generator_agent",
        "confidence": 0.9,
        "created_at": "2026-04-29T00:00:00Z",
        "needs_review": False,
    }


def _prepare_pipeline_with_cases(tmp_settings, cases: list[dict]) -> None:
    """在 outputs/testcases/<project>/<pid>/ 下造一个最小 pipeline 目录，
    含 pipeline_state.json + cases.json（只让 coverage 逻辑吃得下）。"""
    d = pipeline_io.pipeline_dir(PROJECT, PIPELINE_ID, create=True)
    # 最小 state
    state = PipelineState(
        pipeline_id=PIPELINE_ID,
        project=PROJECT,
        question="demo",
        created_at="2026-04-29T00:00:00Z",
        updated_at="2026-04-29T00:00:00Z",
        current_step="completed",
        steps={
            "step1": StepState(status="done"),
            "step2": StepState(status="done"),
            "step3": StepState(status="done"),
            "step4": StepState(status="done"),
        },
        llm_cfg_snapshot=LLMConfigSnapshot(base_url="u", model="m"),
        context_budget=ContextBudgetSnapshot(
            per_call_max_tokens=1, history_max_chars=1,
            retrieval_top_k_chunks=1, retrieval_top_k_kps=1,
            step2_max_parallel=1,
        ),
    )
    pipeline_io.save_state(state)
    (d / pipeline_io.FINAL_CASES_FILE).write_text(
        json.dumps({"cases": cases}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@pytest.fixture
def enable_coverage(tmp_settings):
    from backend import config as cfg_mod
    cfg_mod.FEATURES_STORE_PATH.write_text(
        json.dumps({"enable_coverage_report": True}), encoding="utf-8",
    )


@pytest.fixture
def client(tmp_settings, enable_coverage):
    app = FastAPI()
    app.include_router(routes_coverage.router, prefix="/api/coverage")
    return TestClient(app)


@pytest.fixture
def stub_embed(monkeypatch):
    """让 semantic tier 永远打不中（避免加载 BGE）。"""
    def fake(texts):
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
    monkeypatch.setattr(cov_mod._emb_mod, "embed", fake)


# ---------- guard -----------------------------------------------------------

def test_guard_blocks_when_flag_off(tmp_settings):
    app = FastAPI()
    app.include_router(routes_coverage.router, prefix="/api/coverage")
    c = TestClient(app)
    r = c.get(f"/api/coverage/{PROJECT}/summary")
    assert r.status_code == 403


# ---------- compute ---------------------------------------------------------

def test_compute_happy(client, tmp_settings, stub_embed):
    _prepare_pipeline_with_cases(tmp_settings, [_case_dict("KP_1")])
    kp_store.save_all(PROJECT, [_kp("KP_1")])

    r = client.post(
        f"/api/coverage/{PROJECT}/{PIPELINE_ID}/compute",
        json={"sim_threshold": 0.99, "enable_semantic": True},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total_kps"] == 1
    assert data["total_cases"] == 1
    assert data["tier_counts"]["explicit"] == 1
    # 落盘
    d = pipeline_io.pipeline_dir(PROJECT, PIPELINE_ID)
    assert (d / pipeline_io.COVERAGE_MD_FILE).exists()
    assert (d / pipeline_io.COVERAGE_JSON_FILE).exists()


def test_compute_without_cases_returns_404(client):
    r = client.post(
        f"/api/coverage/{PROJECT}/{PIPELINE_ID}/compute",
        json={"sim_threshold": 0.75},
    )
    assert r.status_code == 404


def test_compute_invalid_pipeline_id_returns_400(client):
    r = client.post(
        f"/api/coverage/{PROJECT}/not_a_pipeline_id/compute",
        json={"sim_threshold": 0.75},
    )
    assert r.status_code == 400


# ---------- cached read -----------------------------------------------------

def test_get_cached_after_compute(client, tmp_settings, stub_embed):
    _prepare_pipeline_with_cases(tmp_settings, [_case_dict("KP_1")])
    kp_store.save_all(PROJECT, [_kp("KP_1")])
    client.post(
        f"/api/coverage/{PROJECT}/{PIPELINE_ID}/compute",
        json={"sim_threshold": 0.99},
    )
    r = client.get(f"/api/coverage/{PROJECT}/{PIPELINE_ID}")
    assert r.status_code == 200
    assert r.json()["total_kps"] == 1


def test_get_cached_404_when_not_computed(client, tmp_settings):
    _prepare_pipeline_with_cases(tmp_settings, [_case_dict("KP_1")])
    r = client.get(f"/api/coverage/{PROJECT}/{PIPELINE_ID}")
    assert r.status_code == 404


# ---------- summary ---------------------------------------------------------

def test_summary_lists_only_computed_pipelines(client, tmp_settings, stub_embed):
    # A：已算出覆盖率的 pipeline
    _prepare_pipeline_with_cases(tmp_settings, [_case_dict("KP_1")])
    kp_store.save_all(PROJECT, [_kp("KP_1")])
    client.post(
        f"/api/coverage/{PROJECT}/{PIPELINE_ID}/compute",
        json={"sim_threshold": 0.99},
    )

    # B：另一个 pipeline 没跑 coverage（只落 state，不写 cases.json 也行）
    other = "pl_20260102_120000_beef"
    pipeline_io.pipeline_dir(PROJECT, other, create=True)

    r = client.get(f"/api/coverage/{PROJECT}/summary")
    assert r.status_code == 200
    items = r.json()["items"]
    pids = [i["pipeline_id"] for i in items]
    assert PIPELINE_ID in pids
    assert other not in pids   # 没算过就不出现
    assert items[0]["total_kps"] == 1
