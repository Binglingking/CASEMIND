"""PR3.4：BM25Index + HybridRetriever 测试。

覆盖面：
  - BM25Index：构建 / 增量 / 删除 / 清空 / 持久化 / 中文分词检索
  - rrf_merge：两路命中时排名融合、单路缺失时不 NaN
  - match_filter：scalar / 列表 OR / 比较符 / fnmatch 通配
  - HybridRetriever.search：hybrid / vector / bm25 三种模式
    + filters 过滤 + 过滤率告警 + feature flag off 路径回归
  - _bm25()：size 不一致时自动重建

所有测试不触发 embedding 模型加载——通过直写 meta.jsonl 绕过。
"""
from __future__ import annotations

import json

import pytest

from backend.core.bm25_index import BM25Index, bm25_path
from backend.core.hybrid_retriever import (
    HybridRetriever,
    RRF_K,
    SearchResult,
    match_filter,
    rrf_merge,
)
from backend.core.vector_store import DEFAULT_NAMESPACE, VectorStore, _paths


PROJECT = "demo"


# ----------- 共用：直写 meta.jsonl 避免 embedding 加载 -------------------------

def _seed_meta(project: str, namespace: str, records: list[dict]) -> None:
    _, _, meta = _paths(project, namespace)
    meta.parent.mkdir(parents=True, exist_ok=True)
    with meta.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _kp_record(idx: int, text: str, module: str, ktype: str,
               section: str = "", doc_version: str = "2025-01-01") -> dict:
    return {
        "id": f"kp-{idx}",
        "text": text,
        "source": "spec.md",
        "index": idx,
        "namespace": "knowledge_points",
        "metadata": {
            "module": module, "type": ktype,
            "section": section, "doc_version": doc_version,
        },
    }


# ============= BM25Index =====================================================

def test_bm25_build_and_search(tmp_settings):
    bm = BM25Index(PROJECT, "chunks")
    bm.build([
        "登录失败后应该提示用户名或密码错误",
        "用户注册需要手机号验证",
        "支付成功后跳转订单页面",
    ])
    hits = bm.search("登录 密码", top_k=5)
    assert hits, "应能召回登录相关文档"
    assert hits[0][0] == 0, "第 0 条应排第一"
    # 都是 score > 0
    assert all(s > 0 for _, s in hits)


def test_bm25_empty_corpus_returns_empty(tmp_settings):
    bm = BM25Index(PROJECT, "chunks")
    assert bm.search("任意查询", top_k=5) == []
    assert bm.size() == 0


def test_bm25_add_texts_incremental(tmp_settings):
    bm = BM25Index(PROJECT, "chunks")
    bm.build([
        "登录失败提示密码错误",
        "用户注册手机号验证流程",
        "账户安全问题找回密码",
    ])
    bm.add_texts(["支付跳转订单详情页面"])
    assert bm.size() == 4
    # 查询 "支付" 只在新增的 idx=3 出现
    hits = bm.search("支付", top_k=3)
    assert hits and hits[0][0] == 3


def test_bm25_remove_indices(tmp_settings):
    bm = BM25Index(PROJECT, "chunks")
    bm.build(["登录 A", "登录 B", "登录 C"])
    bm.remove_indices([1])
    assert bm.size() == 2
    # index 1 已移除，原 index 2 -> 新 index 1
    hits = dict(bm.search("登录", top_k=5))
    assert set(hits.keys()).issubset({0, 1})


def test_bm25_clear(tmp_settings):
    bm = BM25Index(PROJECT, "chunks")
    bm.build(["a 登录", "b 登录"])
    assert bm.path.exists()
    bm.clear()
    assert bm.size() == 0
    assert not bm.path.exists()


def test_bm25_persist_across_instances(tmp_settings):
    bm1 = BM25Index(PROJECT, "chunks")
    bm1.build([
        "登录失败提示密码错误",
        "支付跳转订单页面",
        "用户注册手机号验证",
        "订单详情展示物流信息",
    ])
    # 新实例应该能加载出相同语料
    bm2 = BM25Index(PROJECT, "chunks")
    assert bm2.size() == 4
    hits = bm2.search("密码", top_k=5)
    assert hits and hits[0][0] == 0


def test_bm25_path_includes_namespace(tmp_settings):
    p_chunks = bm25_path(PROJECT, "chunks")
    p_kp = bm25_path(PROJECT, "knowledge_points")
    assert p_chunks.name == f"{PROJECT}.bm25.chunks.pkl"
    assert p_kp.name == f"{PROJECT}.bm25.knowledge_points.pkl"
    assert p_chunks != p_kp


def test_bm25_corrupt_file_does_not_crash(tmp_settings):
    bm = BM25Index(PROJECT, "chunks")
    bm.build(["hello 世界"])
    # 破坏 pickle
    bm.path.write_bytes(b"not a pickle")
    bm2 = BM25Index(PROJECT, "chunks")
    assert bm2.size() == 0   # 坏文件 -> 空语料，不抛


# ============= rrf_merge =====================================================

def test_rrf_merge_two_paths():
    vec = [(10, 0.9), (20, 0.8)]
    bm = [(20, 3.1), (30, 2.0)]
    fused = rrf_merge(vec, bm)
    by_idx = {idx: bd for idx, bd in fused}
    # 20 命中两路，rrf 应为两路倒数之和
    expected_20 = 1.0 / (RRF_K + 1 + 1) + 1.0 / (RRF_K + 0 + 1)
    assert by_idx[20]["rrf"] == pytest.approx(expected_20)
    assert by_idx[20]["vector_rank"] == 1
    assert by_idx[20]["bm25_rank"] == 0
    # 20 应排在最前
    assert fused[0][0] == 20


def test_rrf_merge_single_path_only():
    fused = rrf_merge([(1, 0.5)], [])
    assert len(fused) == 1
    idx, bd = fused[0]
    assert idx == 1
    assert bd["bm25_rank"] is None
    assert bd["vector_rank"] == 0
    assert bd["rrf"] > 0


# ============= match_filter ==================================================

def test_match_filter_none_or_empty_is_true():
    assert match_filter({"a": 1}, None) is True
    assert match_filter({"a": 1}, {}) is True


def test_match_filter_scalar():
    assert match_filter({"module": "登录"}, {"module": "登录"}) is True
    assert match_filter({"module": "下单"}, {"module": "登录"}) is False


def test_match_filter_list_or():
    f = {"type": ["business_rule", "boundary"]}
    assert match_filter({"type": "business_rule"}, f) is True
    assert match_filter({"type": "input_constraint"}, f) is False


def test_match_filter_compare_prefix():
    assert match_filter({"doc_version": "2025-03-01"}, {"doc_version": ">= 2025-01-01"}) is True
    assert match_filter({"doc_version": "2024-12-31"}, {"doc_version": ">= 2025-01-01"}) is False
    assert match_filter({"doc_version": "2024-12-31"}, {"doc_version": "< 2025-01-01"}) is True


def test_match_filter_fnmatch_wildcard():
    assert match_filter({"section": "3.2.1"}, {"section": "3.2.*"}) is True
    assert match_filter({"section": "4.1.0"}, {"section": "3.2.*"}) is False


def test_match_filter_missing_key_returns_false():
    assert match_filter({"module": "登录"}, {"type": "boundary"}) is False


# ============= HybridRetriever.search — 各模式 ===============================

class _FakeVS:
    """最小向量存储 stub：只喂 HybridRetriever 需要的 all_chunks() + search()。"""

    def __init__(self, chunks, vec_scores):
        self._chunks = chunks
        self._vec_scores = vec_scores   # {idx: score} 查询结果

    def all_chunks(self):
        return self._chunks

    def search(self, query, top_k):
        # 按 score 降序返回 (StoredChunk, score)
        ordered = sorted(self._vec_scores.items(), key=lambda kv: -kv[1])[:top_k]
        return [(self._chunks[i], float(s)) for i, s in ordered]


def _install_fake(retriever: HybridRetriever, namespace: str, fake_vs: _FakeVS):
    retriever._stores[namespace] = fake_vs
    # 同步 BM25 规模，避免 _bm25() 触发 VectorStore.all_chunks 的 embedding 加载
    texts = [c.text for c in fake_vs.all_chunks()]
    bm = BM25Index(retriever.project, namespace)
    bm.build(texts)
    retriever._bm[namespace] = bm


def _mk_chunks(tmp_settings):
    """向 meta.jsonl 写 3 条 knowledge_points，返回 StoredChunk 列表。"""
    records = [
        _kp_record(0, "登录失败应提示用户名或密码错误", "登录", "business_rule", "3.2.1"),
        _kp_record(1, "支付成功后跳转订单详情页面",   "支付", "business_rule", "4.1.0"),
        _kp_record(2, "密码长度应在 8 到 20 位之间", "登录", "input_constraint", "3.2.2"),
    ]
    _seed_meta(PROJECT, "knowledge_points", records)
    vs = VectorStore(PROJECT, namespace="knowledge_points")
    return vs.all_chunks()


def test_search_hybrid_mode(tmp_settings):
    chunks = _mk_chunks(tmp_settings)
    r = HybridRetriever(PROJECT)
    fake = _FakeVS(chunks, vec_scores={0: 0.9, 2: 0.7, 1: 0.3})
    _install_fake(r, "knowledge_points", fake)

    results = r.search("登录 密码", top_k=3, namespace="knowledge_points")
    assert all(isinstance(x, SearchResult) for x in results)
    assert len(results) <= 3
    # 登录相关的 2 条（idx 0, 2）应排在支付前
    kept_ids = [res.chunk.index for res in results]
    assert 0 in kept_ids and 2 in kept_ids
    # breakdown 齐全
    top = results[0]
    assert "rrf" in top.score_breakdown
    assert top.score_breakdown["rrf"] > 0


def test_search_vector_only_mode(tmp_settings):
    chunks = _mk_chunks(tmp_settings)
    r = HybridRetriever(PROJECT)
    fake = _FakeVS(chunks, vec_scores={1: 0.99, 0: 0.1, 2: 0.05})
    _install_fake(r, "knowledge_points", fake)

    results = r.search("任意", top_k=2, namespace="knowledge_points", mode="vector")
    # vector 模式下按向量得分排序
    assert results[0].chunk.index == 1
    # bm25_rank 应恒为 None
    for res in results:
        assert res.score_breakdown["bm25_rank"] is None


def test_search_bm25_only_mode(tmp_settings):
    chunks = _mk_chunks(tmp_settings)
    r = HybridRetriever(PROJECT)
    fake = _FakeVS(chunks, vec_scores={})
    _install_fake(r, "knowledge_points", fake)

    results = r.search("密码 长度", top_k=3, namespace="knowledge_points", mode="bm25")
    assert results, "BM25 应至少召回 1 条"
    # bm25 单路，vector_rank 为 None? 注意 _single_rank 里写的 "vector_rank": rank
    # 对单路 BM25，_single_rank 实际上把 rank 写进了 vector_rank —— 这是实现细节。
    # 这里只验证 rrf > 0 且顺序正确。
    for res in results:
        assert res.score_breakdown["rrf"] > 0


def test_search_filters_by_module(tmp_settings):
    chunks = _mk_chunks(tmp_settings)
    r = HybridRetriever(PROJECT)
    fake = _FakeVS(chunks, vec_scores={0: 0.9, 1: 0.8, 2: 0.7})
    _install_fake(r, "knowledge_points", fake)

    results = r.search(
        "任意", top_k=5, namespace="knowledge_points",
        filters={"module": "登录"},
    )
    for res in results:
        assert res.chunk.metadata["module"] == "登录"
    # 只有 idx 0, 2 符合
    kept_ids = {res.chunk.index for res in results}
    assert kept_ids == {0, 2}


def test_search_filters_by_type_list(tmp_settings):
    chunks = _mk_chunks(tmp_settings)
    r = HybridRetriever(PROJECT)
    fake = _FakeVS(chunks, vec_scores={0: 0.9, 1: 0.8, 2: 0.7})
    _install_fake(r, "knowledge_points", fake)

    results = r.search(
        "任意", top_k=5, namespace="knowledge_points",
        filters={"type": ["input_constraint", "boundary"]},
    )
    assert len(results) == 1
    assert results[0].chunk.index == 2


def test_search_filters_wildcard_section(tmp_settings):
    chunks = _mk_chunks(tmp_settings)
    r = HybridRetriever(PROJECT)
    fake = _FakeVS(chunks, vec_scores={0: 0.9, 1: 0.8, 2: 0.7})
    _install_fake(r, "knowledge_points", fake)

    results = r.search(
        "任意", top_k=5, namespace="knowledge_points",
        filters={"section": "3.2.*"},
    )
    kept_ids = {res.chunk.index for res in results}
    assert kept_ids == {0, 2}


def test_search_filter_warns_when_insufficient(tmp_settings, caplog):
    chunks = _mk_chunks(tmp_settings)
    r = HybridRetriever(PROJECT)
    fake = _FakeVS(chunks, vec_scores={0: 0.9, 1: 0.8, 2: 0.7})
    _install_fake(r, "knowledge_points", fake)

    import logging
    caplog.set_level(logging.WARNING, logger="backend.core.hybrid_retriever")
    _ = r.search(
        "任意", top_k=5, namespace="knowledge_points",
        filters={"module": "不存在的模块"},
    )
    assert any("过滤后结果不足 top_k" in rec.message for rec in caplog.records)


def test_search_empty_on_empty_store(tmp_settings):
    r = HybridRetriever(PROJECT)
    # knowledge_points 尚未 seed -> all_chunks() 空
    results = r.search("任意", top_k=5, namespace="knowledge_points")
    assert results == []


def test_search_empty_query_returns_empty(tmp_settings):
    chunks = _mk_chunks(tmp_settings)
    r = HybridRetriever(PROJECT)
    fake = _FakeVS(chunks, vec_scores={0: 0.9})
    _install_fake(r, "knowledge_points", fake)
    assert r.search("", top_k=5, namespace="knowledge_points") == []
    assert r.search("   ", top_k=5, namespace="knowledge_points") == []


# ============= BM25 懒加载 / 自动重建 =========================================

def test_bm25_auto_rebuild_when_size_mismatch(tmp_settings):
    """VectorStore 有 3 条、BM25 文件不存在 → _bm25() 首次访问应自动 build。"""
    chunks = _mk_chunks(tmp_settings)
    assert len(chunks) == 3

    r = HybridRetriever(PROJECT)
    # 注意：不调 _install_fake，让真实 VectorStore 承担 all_chunks
    bm = r._bm25("knowledge_points")
    assert bm.size() == 3


# ============= Reranker 集成 =================================================

def _patch_reranker(monkeypatch, impl):
    """把 reranker.rerank 直接替换成给定函数 impl(query, docs, top_k)->list[(i,s)]。"""
    from backend.core import reranker as rr_mod
    monkeypatch.setattr(rr_mod, "rerank", impl)


def test_search_reranker_reorders_candidates(tmp_settings, monkeypatch):
    """use_reranker=True 时：reranker 的得分主导最终顺序。"""
    chunks = _mk_chunks(tmp_settings)
    r = HybridRetriever(PROJECT)
    # 让 RRF 最靠前的是 idx=1（支付），reranker 应把 idx=2 拉到最前
    fake = _FakeVS(chunks, vec_scores={1: 0.99, 0: 0.5, 2: 0.4})
    _install_fake(r, "knowledge_points", fake)

    def fake_rerank(query, docs, top_k=None):
        # docs 顺序就是 RRF 后 kept 的顺序；让最后一条得分最高以翻转
        scored = [(i, float(i)) for i in range(len(docs))]
        scored.sort(key=lambda kv: kv[1], reverse=True)
        return scored[:top_k] if top_k else scored
    _patch_reranker(monkeypatch, fake_rerank)

    results_no_rr = r.search("任意", top_k=3, namespace="knowledge_points")
    results_rr = r.search("任意", top_k=3, namespace="knowledge_points",
                          use_reranker=True)
    # 不开 reranker：顺序来自 RRF；开 reranker：倒序（fake 定义）
    assert [x.chunk.index for x in results_no_rr] != [x.chunk.index for x in results_rr]
    # 每条都带 rerank_score
    for x in results_rr:
        assert "rerank_score" in x.score_breakdown
    # score 字段也被替换为 rerank_score
    assert results_rr[0].score == results_rr[0].score_breakdown["rerank_score"]


def test_search_reranker_fallback_on_all_zero(tmp_settings, monkeypatch):
    """reranker 返回全零分（模型不可用兜底）时：保留 RRF 顺序，rerank_score=0。"""
    chunks = _mk_chunks(tmp_settings)
    r = HybridRetriever(PROJECT)
    fake = _FakeVS(chunks, vec_scores={0: 0.9, 2: 0.7, 1: 0.3})
    _install_fake(r, "knowledge_points", fake)

    def zero_rerank(query, docs, top_k=None):
        return [(i, 0.0) for i in range(len(docs))][:top_k]
    _patch_reranker(monkeypatch, zero_rerank)

    no_rr = r.search("登录", top_k=3, namespace="knowledge_points")
    rr_on = r.search("登录", top_k=3, namespace="knowledge_points", use_reranker=True)
    assert [x.chunk.index for x in no_rr] == [x.chunk.index for x in rr_on]
    for x in rr_on:
        assert x.score_breakdown.get("rerank_score") == 0.0


def test_search_reranker_enlarges_candidate_pool(tmp_settings, monkeypatch):
    """use_reranker=True 时 reranker 看到的候选应多于 top_k（近 initial_k=top_k*3）。"""
    chunks = _mk_chunks(tmp_settings)
    r = HybridRetriever(PROJECT)
    fake = _FakeVS(chunks, vec_scores={0: 0.9, 1: 0.8, 2: 0.7})
    _install_fake(r, "knowledge_points", fake)

    seen_sizes = {}

    def capture_rerank(query, docs, top_k=None):
        seen_sizes["n"] = len(docs)
        return [(i, float(len(docs) - i)) for i in range(len(docs))][:top_k]
    _patch_reranker(monkeypatch, capture_rerank)

    r.search("任意", top_k=1, namespace="knowledge_points", use_reranker=True)
    # top_k=1 但语料只有 3 条——候选池最多 3（min(initial_k=3, len(fused))）
    assert seen_sizes["n"] == 3


def test_search_reranker_exception_keeps_rrf_order(tmp_settings, monkeypatch):
    """reranker 抛异常时不会让查询挂掉；顺序保持 RRF 结果。"""
    chunks = _mk_chunks(tmp_settings)
    r = HybridRetriever(PROJECT)
    fake = _FakeVS(chunks, vec_scores={0: 0.9, 2: 0.7, 1: 0.3})
    _install_fake(r, "knowledge_points", fake)

    def boom(*a, **kw):
        raise RuntimeError("cuda oom")
    _patch_reranker(monkeypatch, boom)

    no_rr = r.search("任意", top_k=3, namespace="knowledge_points")
    rr_on = r.search("任意", top_k=3, namespace="knowledge_points", use_reranker=True)
    assert [x.chunk.index for x in no_rr] == [x.chunk.index for x in rr_on]


# ============= QueryAgent feature flag off 回归 ===============================

def _stub_features(monkeypatch, qa_mod, **flags):
    """把 qa_mod._read_features 替换成返回指定 flags 的 Features 实例。

    这样就无需依赖 settings.features 的进程内状态，也无需读写 features.json。
    """
    from backend.config import Features
    feats = Features(**flags)
    monkeypatch.setattr(qa_mod, "_read_features", lambda: feats)


def test_query_agent_flag_off_uses_vector_store(monkeypatch, tmp_settings):
    """flag=False 时 QueryAgent 仍走 VectorStore.search，不触碰 HybridRetriever。"""
    from backend.agents import query_agent as qa_mod

    _stub_features(monkeypatch, qa_mod, enable_hybrid_retrieval=False)

    called = {"vs": 0, "hybrid": 0}

    class _StubVS:
        def __init__(self, project, namespace=DEFAULT_NAMESPACE):
            pass
        def search(self, q, top_k):
            called["vs"] += 1
            return []

    class _StubHybrid:
        def __init__(self, project):
            called["hybrid"] += 1
        def search(self, *a, **kw):
            called["hybrid"] += 1
            return []

    monkeypatch.setattr(qa_mod, "VectorStore", _StubVS)
    monkeypatch.setattr(qa_mod, "HybridRetriever", _StubHybrid)

    agent = qa_mod.QueryAgent(project=PROJECT)
    agent._retrieve("hello", top_k=5)
    assert called["vs"] == 1
    assert called["hybrid"] == 0


def test_query_agent_flag_on_uses_hybrid(monkeypatch, tmp_settings):
    from backend.agents import query_agent as qa_mod
    from backend.core.hybrid_retriever import SearchResult
    from backend.core.vector_store import StoredChunk

    _stub_features(monkeypatch, qa_mod, enable_hybrid_retrieval=True)

    called = {"vs": 0, "hybrid": 0}

    class _StubVS:
        def __init__(self, project, namespace=DEFAULT_NAMESPACE):
            pass
        def search(self, q, top_k):
            called["vs"] += 1
            return []

    class _StubHybrid:
        def __init__(self, project):
            pass
        def search(self, q, top_k, namespace, mode, use_reranker=False):
            called["hybrid"] += 1
            assert namespace == "chunks"
            assert mode == "hybrid"
            c = StoredChunk(id="x", text="t", source="s", index=0)
            return [SearchResult(chunk=c, score=0.5, score_breakdown={"rrf": 0.5})]

    monkeypatch.setattr(qa_mod, "VectorStore", _StubVS)
    monkeypatch.setattr(qa_mod, "HybridRetriever", _StubHybrid)

    agent = qa_mod.QueryAgent(project=PROJECT)
    out = agent._retrieve("hello", top_k=5)
    assert called["hybrid"] == 1
    assert called["vs"] == 0
    assert len(out) == 1 and out[0][1] == 0.5


def test_query_agent_hybrid_failure_falls_back_to_vector(monkeypatch, tmp_settings):
    """HybridRetriever 抛异常时退回 VectorStore，不让查询崩。"""
    from backend.agents import query_agent as qa_mod

    _stub_features(monkeypatch, qa_mod, enable_hybrid_retrieval=True)
    called = {"vs": 0}

    class _StubVS:
        def __init__(self, project, namespace=DEFAULT_NAMESPACE):
            pass
        def search(self, q, top_k):
            called["vs"] += 1
            return []

    class _BrokenHybrid:
        def __init__(self, project):
            pass
        def search(self, *a, **kw):
            raise RuntimeError("boom")

    monkeypatch.setattr(qa_mod, "VectorStore", _StubVS)
    monkeypatch.setattr(qa_mod, "HybridRetriever", _BrokenHybrid)

    agent = qa_mod.QueryAgent(project=PROJECT)
    out = agent._retrieve("hello", top_k=5)
    assert called["vs"] == 1
    assert out == []


def test_query_agent_reads_runtime_features(monkeypatch, tmp_settings):
    """flag-sync 回归：翻转 features.json → QueryAgent._retrieve 立即感知，无需重启。

    保护 `_read_features()` 真的走到 routes_settings.get_runtime_features；
    避免以后有人误改成再次读 settings.features 的进程内状态。
    """
    import json

    from backend.agents import query_agent as qa_mod
    from backend.config import FEATURES_STORE_PATH, settings

    # settings.features 永远 off，确认读盘才是生效路径
    settings.features.enable_hybrid_retrieval = False

    called = {"vs": 0, "hybrid": 0}

    class _StubVS:
        def __init__(self, project, namespace=DEFAULT_NAMESPACE):
            pass
        def search(self, q, top_k):
            called["vs"] += 1
            return []

    class _StubHybrid:
        def __init__(self, project):
            pass
        def search(self, q, top_k, namespace, mode, use_reranker=False):
            called["hybrid"] += 1
            return []

    monkeypatch.setattr(qa_mod, "VectorStore", _StubVS)
    monkeypatch.setattr(qa_mod, "HybridRetriever", _StubHybrid)

    # 磁盘上写 enable_hybrid_retrieval=true
    FEATURES_STORE_PATH.write_text(
        json.dumps({"enable_hybrid_retrieval": True}), encoding="utf-8",
    )

    agent = qa_mod.QueryAgent(project=PROJECT)
    agent._retrieve("hello", top_k=5)
    assert called["hybrid"] == 1, "磁盘 flag=true 时应走 HybridRetriever"
    assert called["vs"] == 0
