"""PR1.5：features flag API 测试。

GET → 默认全部 False
PUT → 部分更新 + 持久化
GET 再读 → 反映更新
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.api import routes_settings


@pytest.fixture
def client(tmp_settings):
    """用本地路由单独建 app，避免触发 main.py 里的全局初始化副作用。"""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(routes_settings.router, prefix="/api/settings")
    return TestClient(app)


def test_get_features_defaults_all_false(client):
    r = client.get("/api/settings/features")
    assert r.status_code == 200
    data = r.json()
    for key in [
        "enable_knowledge_extraction",
        "enable_hybrid_retrieval",
        "enable_case_gen_pipeline",
        "enable_coverage_report",
        "enable_conflict_detection",
        "enable_feedback_loop",
        "enable_reranker",
    ]:
        assert data[key] is False


def test_put_features_partial_update(client, tmp_settings):
    r = client.put("/api/settings/features", json={
        "enable_knowledge_extraction": True,
        "enable_hybrid_retrieval": True,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["enable_knowledge_extraction"] is True
    assert data["enable_hybrid_retrieval"] is True
    # 未提交的字段保持 False
    assert data["enable_case_gen_pipeline"] is False

    # 持久化：重新 GET 仍返回更新值
    r2 = client.get("/api/settings/features")
    assert r2.json()["enable_knowledge_extraction"] is True


def test_put_empty_body_rejected(client):
    r = client.put("/api/settings/features", json={})
    assert r.status_code == 400


def test_runtime_features_reads_disk(tmp_settings):
    """业务代码应该通过 get_runtime_features() 读取当前生效开关。"""
    from backend import config as cfg_mod
    # 手写一份磁盘上的 features.json
    cfg_mod.FEATURES_STORE_PATH.write_text(
        json.dumps({"enable_hybrid_retrieval": True}, ensure_ascii=False),
        encoding="utf-8",
    )
    feats = routes_settings.get_runtime_features()
    assert feats.enable_hybrid_retrieval is True
    # 未设置的字段走默认
    assert feats.enable_knowledge_extraction is False


def test_runtime_features_falls_back_on_corrupt_file(tmp_settings):
    from backend import config as cfg_mod
    cfg_mod.FEATURES_STORE_PATH.write_text("not json {{", encoding="utf-8")
    feats = routes_settings.get_runtime_features()
    assert feats.enable_knowledge_extraction is False
