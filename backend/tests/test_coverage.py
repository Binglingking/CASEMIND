"""PR4.7：CoverageAnalyzer 测试。

策略：monkey-patch `coverage._emb_mod.embed` 返回确定向量，避免加载 BGE。
覆盖：
  - 三层命中（explicit / same_chunk / semantic）优先级
  - 未命中（uncovered）
  - 语义关闭（enable_semantic=False）路径
  - embedding 不可用 → semantic_skipped=True
  - render_markdown 包含关键字段
  - save 产出 md + json 两个文件
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from backend.analytics import coverage as cov_mod
from backend.analytics.coverage import (
    WEIGHT_EXPLICIT,
    WEIGHT_SAME_CHUNK,
    WEIGHT_SEMANTIC,
    compute,
    render_markdown,
    save,
)
from backend.schemas.knowledge_point import KnowledgePoint, KPSource
from backend.schemas.test_case import CaseStep, SourceRef, TestCase


def _kp(kp_id: str, module: str = "登录", ktype: str = "business_rule",
        chunk_id: str = "a.md::0::h", content: str = "rule") -> KnowledgePoint:
    return KnowledgePoint(
        kp_id=kp_id, type=ktype, content=content, module=module,
        source=KPSource(file="a.md", chunk_id=chunk_id),
        doc_version="v1", extracted_at="2026-01-01T00:00:00Z",
    )


def _case(case_id: str, kp: str | None = None, chunk_id: str | None = None,
          title: str = "登录成功") -> TestCase:
    # SourceRef 要求 kp_id/chunk_id 至少一个非空——都不给时塞一个不会命中 KP 的假 chunk_id
    if kp is None and chunk_id is None:
        chunk_id = "__no_match__::0::x"
    refs = [SourceRef(kp_id=kp, chunk_id=chunk_id, file="a.md")]
    return TestCase(
        case_id=case_id, title=title, priority="P1", category="正常",
        feature_point="FP_登录_001", related_feature_points=[],
        preconditions=[], steps=[CaseStep(step=1, action="登录", data="x")],
        expected_result="成功", source_refs=refs,
        generated_by="case_generator_agent", confidence=0.9,
        created_at="2026-04-29T00:00:00Z", needs_review=False,
    )


def _fake_embed_factory(mapping: dict[str, list[float]]):
    dim = len(next(iter(mapping.values())))
    def fn(texts: list[str]) -> np.ndarray:
        out = []
        for t in texts:
            v = mapping.get(t)
            if v is None:
                # 唯一化的 fallback（避免误中 semantic）
                import hashlib
                h = int(hashlib.md5(t.encode("utf-8")).hexdigest(), 16)
                vec = [0.0] * dim
                vec[h % dim] = 1.0
                out.append(vec)
            else:
                out.append(v)
        arr = np.array(out, dtype="float32")
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms
    return fn


# ---- Tier 1: explicit --------------------------------------------------

def test_explicit_hit(monkeypatch, tmp_settings):
    k = _kp("KP_1")
    c = _case("TC_1", kp="KP_1")
    # semantic 永远打不中
    monkeypatch.setattr(cov_mod._emb_mod, "embed",
                        _fake_embed_factory({"zzz": [1.0, 0.0]}))
    r = compute([c], [k], project="demo", sim_threshold=0.99)
    assert r.by_kp[0].tier == "explicit"
    assert r.by_kp[0].score == WEIGHT_EXPLICIT
    assert r.by_kp[0].matched_case_ids == ["TC_1"]
    assert r.uncovered_kp_ids == []


# ---- Tier 2: same_chunk（比 explicit 弱，explicit 存在时不降级） ----------

def test_same_chunk_hit_when_no_explicit(monkeypatch, tmp_settings):
    k = _kp("KP_1", chunk_id="a.md::0::h")
    c = _case("TC_1", chunk_id="a.md::0::h")  # 只有 chunk_id，没 kp_id 指向
    monkeypatch.setattr(cov_mod._emb_mod, "embed",
                        _fake_embed_factory({"zzz": [1.0, 0.0]}))
    r = compute([c], [k], project="demo", sim_threshold=0.99)
    assert r.by_kp[0].tier == "same_chunk"
    assert r.by_kp[0].score == WEIGHT_SAME_CHUNK


def test_explicit_beats_same_chunk(monkeypatch, tmp_settings):
    """同一 KP 同时被 explicit 和 same_chunk 命中 → 保留 explicit。"""
    k = _kp("KP_1", chunk_id="a.md::0::h")
    c1 = _case("TC_1", kp="KP_1")                        # explicit
    c2 = _case("TC_2", chunk_id="a.md::0::h")            # same_chunk
    monkeypatch.setattr(cov_mod._emb_mod, "embed",
                        _fake_embed_factory({"zzz": [1.0, 0.0]}))
    r = compute([c1, c2], [k], project="demo", sim_threshold=0.99)
    assert r.by_kp[0].tier == "explicit"
    # matched_case_ids 只存当前 tier 的命中 case
    assert r.by_kp[0].matched_case_ids == ["TC_1"]


# ---- Tier 3: semantic --------------------------------------------------

def test_semantic_hit(monkeypatch, tmp_settings):
    k = _kp("KP_1", content="登录成功后跳转首页")
    c = _case("TC_1", title="登录成功")
    # 让两者 embedding 完全一致 → cos=1，必过阈值
    kp_text = cov_mod._kp_embed_text(k)
    case_text = cov_mod._case_embed_text(c)
    monkeypatch.setattr(cov_mod._emb_mod, "embed",
                        _fake_embed_factory({
                            kp_text: [1.0, 0.0],
                            case_text: [1.0, 0.0],
                        }))
    r = compute([c], [k], project="demo", sim_threshold=0.75)
    assert r.by_kp[0].tier == "semantic"
    assert r.by_kp[0].score == WEIGHT_SEMANTIC
    assert r.by_kp[0].best_similarity is not None
    assert r.by_kp[0].best_similarity >= 0.99


def test_semantic_below_threshold_uncovered(monkeypatch, tmp_settings):
    k = _kp("KP_1")
    c = _case("TC_1")
    # 正交向量 → cos=0
    monkeypatch.setattr(cov_mod._emb_mod, "embed",
                        _fake_embed_factory({
                            cov_mod._kp_embed_text(k): [1.0, 0.0],
                            cov_mod._case_embed_text(c): [0.0, 1.0],
                        }))
    r = compute([c], [k], project="demo", sim_threshold=0.75)
    assert r.by_kp[0].tier == "uncovered"
    assert r.by_kp[0].score == 0.0
    assert r.uncovered_kp_ids == ["KP_1"]


# ---- enable_semantic=False -------------------------------------------

def test_enable_semantic_false_skips_embedding(tmp_settings):
    """enable_semantic=False → embedding 不被调用。"""
    k = _kp("KP_1")
    c = _case("TC_1", kp="KP_1")
    # 不 monkey-patch embed；如果被调用，会去加载真实 BGE，测试会慢/失败
    r = compute([c], [k], project="demo",
                sim_threshold=0.75, enable_semantic=False)
    assert r.by_kp[0].tier == "explicit"
    assert r.semantic_skipped is False  # 明确关闭不是"跳过"，只是没启用


def test_embedding_failure_marks_skipped(monkeypatch, tmp_settings):
    k = _kp("KP_1")
    c = _case("TC_1")
    def boom(texts): raise RuntimeError("faiss missing")
    monkeypatch.setattr(cov_mod._emb_mod, "embed", boom)
    r = compute([c], [k], project="demo")
    assert r.semantic_skipped is True
    assert r.by_kp[0].tier == "uncovered"  # 没有 explicit / same_chunk，且 semantic 被跳过


# ---- 聚合 --------------------------------------------------------------

def test_weighted_score_and_ratios(monkeypatch, tmp_settings):
    """3 个 KP：1 explicit + 1 same_chunk + 1 uncovered → 加权分 = (1+0.7+0)/3。"""
    k1 = _kp("KP_1")
    k2 = _kp("KP_2", chunk_id="b.md::0::h")
    k3 = _kp("KP_3", chunk_id="c.md::0::h")
    c1 = _case("TC_1", kp="KP_1")
    c2 = _case("TC_2", chunk_id="b.md::0::h")
    # 让 semantic 完全不命中
    monkeypatch.setattr(cov_mod._emb_mod, "embed",
                        _fake_embed_factory({"zzz": [1.0, 0.0]}))
    r = compute([c1, c2], [k1, k2, k3], project="demo", sim_threshold=0.99)
    assert r.total_kps == 3
    assert r.tier_counts["explicit"] == 1
    assert r.tier_counts["same_chunk"] == 1
    assert r.tier_counts["uncovered"] == 1
    expected = (WEIGHT_EXPLICIT + WEIGHT_SAME_CHUNK + 0.0) / 3
    assert abs(r.weighted_score - expected) < 1e-6


def test_by_module_and_by_type(monkeypatch, tmp_settings):
    k1 = _kp("KP_1", module="登录", ktype="business_rule")
    k2 = _kp("KP_2", module="首页", ktype="acceptance_criteria")
    c = _case("TC_1", kp="KP_1")
    # dim 要 ≥ 4 才能让 hash fallback 分散到不同维度，否则所有 1-维向量 cos=1
    monkeypatch.setattr(cov_mod._emb_mod, "embed",
                        _fake_embed_factory({"zzz": [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]}))
    r = compute([c], [k1, k2], project="demo", sim_threshold=0.99)
    assert r.by_module["登录"]["covered"] == 1
    assert r.by_module["首页"]["covered"] == 0
    assert r.by_type["business_rule"]["covered"] == 1
    assert r.by_type["acceptance_criteria"]["covered"] == 0


# ---- 空输入 ------------------------------------------------------------

def test_empty_kps_returns_empty_report(tmp_settings):
    r = compute([], [], project="demo")
    assert r.total_kps == 0
    assert r.weighted_score == 0.0
    assert r.by_kp == []


def test_empty_cases_all_uncovered(tmp_settings):
    k = _kp("KP_1")
    r = compute([], [k], project="demo", enable_semantic=False)
    assert r.by_kp[0].tier == "uncovered"
    assert r.uncovered_kp_ids == ["KP_1"]


# ---- 渲染 / 保存 -------------------------------------------------------

def test_render_markdown_mentions_totals(monkeypatch, tmp_settings):
    k = _kp("KP_1")
    c = _case("TC_1", kp="KP_1")
    monkeypatch.setattr(cov_mod._emb_mod, "embed",
                        _fake_embed_factory({"zzz": [1.0]}))
    r = compute([c], [k], project="demo", pipeline_id="pl_x")
    md = render_markdown(r)
    assert "demo" in md
    assert "pl_x" in md
    assert "总 KP 数" in md
    assert "覆盖层级分布" in md
    assert "explicit" in md


def test_save_writes_md_and_json(monkeypatch, tmp_settings, tmp_path):
    k = _kp("KP_1")
    c = _case("TC_1", kp="KP_1")
    monkeypatch.setattr(cov_mod._emb_mod, "embed",
                        _fake_embed_factory({"zzz": [1.0]}))
    r = compute([c], [k], project="demo", pipeline_id="pl_x")
    md_p, json_p = save(r, tmp_path)
    assert md_p.exists() and json_p.exists()
    data = json.loads(json_p.read_text(encoding="utf-8"))
    assert data["total_kps"] == 1
    assert data["by_kp"][0]["tier"] == "explicit"
