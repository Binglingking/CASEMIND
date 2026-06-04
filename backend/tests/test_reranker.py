"""PR8.1：core/reranker.py 单元测试。

策略：
  - 不触发真正的 bge-reranker 下载；全部 monkey-patch sentence_transformers.CrossEncoder
  - 验证：加载失败 → 原序降级；推理失败 → 原序降级；正常路径 → 按分数降序
"""
from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from backend.core import reranker as rr_mod


class _FakeCE:
    """CrossEncoder 的最小替身：predict 返回 query 与 doc 共现字符数。"""
    def __init__(self, name: str) -> None:
        self.name = name

    def predict(self, pairs, show_progress_bar: bool = False):
        scores = []
        for q, d in pairs:
            q_set = set(q)
            score = sum(1 for ch in (d or "") if ch in q_set)
            scores.append(float(score))
        return np.array(scores, dtype="float32")


@pytest.fixture(autouse=True)
def _reset():
    rr_mod._reset_for_tests()
    yield
    rr_mod._reset_for_tests()


def _inject_st_module(monkeypatch, ce_cls) -> None:
    """在 sys.modules 注入一个伪造的 sentence_transformers，只暴露 CrossEncoder。

    测试环境里真实 sentence_transformers 可能未安装；reranker._load() 里是延迟
    `from sentence_transformers import CrossEncoder`，所以这里只要覆盖 sys.modules
    就能让那行 import 拿到我们的替身。
    """
    fake = types.ModuleType("sentence_transformers")
    fake.CrossEncoder = ce_cls
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)


def _install_ok_ce(monkeypatch):
    _inject_st_module(monkeypatch, _FakeCE)


def _install_broken_ce(monkeypatch, err: Exception):
    def _boom(*a, **kw):
        raise err
    _inject_st_module(monkeypatch, _boom)


# ---- 边界 ----------------------------------------------------------------

def test_rerank_empty_query_returns_empty(monkeypatch):
    _install_ok_ce(monkeypatch)
    assert rr_mod.rerank("", ["a", "b"]) == []


def test_rerank_empty_docs_returns_empty(monkeypatch):
    _install_ok_ce(monkeypatch)
    assert rr_mod.rerank("登录", []) == []


def test_rerank_top_k_zero_returns_empty(monkeypatch):
    _install_ok_ce(monkeypatch)
    assert rr_mod.rerank("登录", ["a"], top_k=0) == []


# ---- 正常路径 ------------------------------------------------------------

def test_rerank_orders_by_score_desc(monkeypatch):
    _install_ok_ce(monkeypatch)
    docs = [
        "支付成功跳转订单页",
        "登录失败提示密码错误",       # 与 '登录 密码' 重叠最多
        "用户注册手机号验证",
    ]
    out = rr_mod.rerank("登录 密码", docs)
    assert len(out) == 3
    # 第一位应是 docs[1]（与 query 共现最多）
    assert out[0][0] == 1
    assert out[0][1] >= out[1][1] >= out[2][1]


def test_rerank_top_k_truncates(monkeypatch):
    _install_ok_ce(monkeypatch)
    docs = ["a登录", "b登录", "c登录", "d登录"]
    out = rr_mod.rerank("登录", docs, top_k=2)
    assert len(out) == 2


def test_rerank_top_k_larger_than_docs(monkeypatch):
    _install_ok_ce(monkeypatch)
    out = rr_mod.rerank("登录", ["登录 a", "注册 b"], top_k=99)
    # 超界不会炸，返回全部
    assert len(out) == 2


# ---- 降级：加载失败 ------------------------------------------------------

def test_rerank_returns_identity_when_model_load_fails(monkeypatch):
    _install_broken_ce(monkeypatch, RuntimeError("cannot fetch from hub"))
    docs = ["x", "y", "z"]
    out = rr_mod.rerank("q", docs)
    # 原序且 score 全 0
    assert [i for i, _ in out] == [0, 1, 2]
    assert all(s == 0.0 for _, s in out)
    # 失败后再调一次也不应重试加载（_load_failed 生效）
    out2 = rr_mod.rerank("q", docs)
    assert out2 == out


def test_rerank_identity_respects_top_k_on_failure(monkeypatch):
    _install_broken_ce(monkeypatch, RuntimeError("boom"))
    out = rr_mod.rerank("q", ["a", "b", "c", "d"], top_k=2)
    assert [i for i, _ in out] == [0, 1]


# ---- 降级：推理失败 ------------------------------------------------------

class _PredictFailsCE:
    def __init__(self, name: str) -> None:
        pass

    def predict(self, pairs, show_progress_bar: bool = False):
        raise RuntimeError("cuda oom")


def test_rerank_returns_identity_when_predict_fails(monkeypatch):
    _inject_st_module(monkeypatch, _PredictFailsCE)
    out = rr_mod.rerank("q", ["a", "b"])
    assert [i for i, _ in out] == [0, 1]
    assert all(s == 0.0 for _, s in out)


# ---- 诊断 ----------------------------------------------------------------

def test_is_available_before_load(monkeypatch):
    _install_ok_ce(monkeypatch)
    assert rr_mod.is_available() is False
    rr_mod.rerank("q", ["a"])  # 触发加载
    assert rr_mod.is_available() is True


def test_is_available_after_load_failure(monkeypatch):
    _install_broken_ce(monkeypatch, RuntimeError("boom"))
    rr_mod.rerank("q", ["a"])
    assert rr_mod.is_available() is False
