"""PR4.4：Step 3 Merger Agent 测试。

策略：
  - monkey-patch `_emb_mod.embed`，返回确定性向量；**不加载真实 BGE 模型**
  - monkey-patch `_llm_mod.chat`，不发 HTTP
覆盖：
  - 本地去重：相似阈值以上归簇、保留 confidence 最高、source_refs 合并
  - 无重复 → dedupe_log 空
  - skip_integration=True → 不调 LLM
  - LLM 集成用例 happy path
  - 集成用例 related_feature_points<2 被过滤
  - 集成用例引用未知 kp_id 被过滤
  - LLM 失败 → merged_cases 仍保留，error 非空
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from backend.agents.case_gen import merger as merger_mod
from backend.agents.case_gen.merger import Merger
from backend.core.llm import LLMConfig
from backend.schemas.feature_point import FeaturePoint
from backend.schemas.test_case import CaseStep, SourceRef, TestCase


PROJECT = "demo"


def _cfg() -> LLMConfig:
    return LLMConfig(base_url="https://x/v1", api_key="k", model="m")


def _case(case_id: str, fp_id: str = "FP_登录_001",
          title: str | None = None,
          category: str = "正常",
          confidence: float = 0.9,
          kp: str = "KP_登录_br_0001",
          chunk_id: str | None = None) -> TestCase:
    refs = [SourceRef(kp_id=kp, chunk_id=chunk_id, file="f.md")]
    return TestCase(
        case_id=case_id,
        title=title or case_id,
        priority="P1",
        category=category,
        feature_point=fp_id,
        related_feature_points=[],
        preconditions=[],
        steps=[CaseStep(step=1, action="操作", data="x")],
        expected_result="成功",
        source_refs=refs,
        generated_by="case_generator_agent",
        confidence=confidence,
        created_at="2026-04-28T00:00:00Z",
        needs_review=False,
    )


def _fp(fp_id: str, module: str = "登录") -> FeaturePoint:
    return FeaturePoint(
        fp_id=fp_id, name=fp_id, description="desc",
        module=module, related_kp_ids=[],
    )


def _fake_embed_factory(vec_by_text: dict[str, list[float]]):
    """按文本精确映射到向量；找不到就给一个全零向量。"""
    dim = len(next(iter(vec_by_text.values())))
    def fn(texts: list[str]) -> np.ndarray:
        out = []
        for t in texts:
            v = vec_by_text.get(t)
            if v is None:
                # 任一文本缺失 → 用唯一向量避免误判重复
                import hashlib
                h = int(hashlib.md5(t.encode("utf-8")).hexdigest(), 16)
                fallback = [0.0] * dim
                fallback[h % dim] = 1.0
                out.append(fallback)
            else:
                out.append(v)
        arr = np.array(out, dtype="float32")
        # 归一化（模拟 BGE normalize_embeddings=True）
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms
    return fn


# ---- 本地去重 ------------------------------------------------------------

def test_dedupe_similar_cases_kept_highest_confidence(monkeypatch, tmp_settings):
    """两条文本几乎一致的用例应归为一簇；保留 confidence 更高的那条。"""
    c1 = _case("TC_1", confidence=0.8, kp="KP_a", title="登录成功")
    c2 = _case("TC_2", confidence=0.95, kp="KP_b", title="登录成功")  # 更高
    c3 = _case("TC_3", confidence=0.7, title="忘记密码", category="异常")

    from backend.agents.case_gen.merger import _case_embed_text
    vecs = {
        _case_embed_text(c1): [1.0, 0.0, 0.0],
        _case_embed_text(c2): [1.0, 0.0, 0.0],   # 与 c1 完全相同 → sim=1
        _case_embed_text(c3): [0.0, 1.0, 0.0],   # 与前两者正交
    }
    monkeypatch.setattr(merger_mod._emb_mod, "embed", _fake_embed_factory(vecs))

    agent = Merger(project=PROJECT)
    result = agent.run(
        cases=[c1, c2, c3],
        feature_points=[_fp("FP_登录_001")],
        allowed_kp_ids={"KP_a", "KP_b"},
        llm_cfg=_cfg(),
        skip_integration=True,
    )
    kept = {c.case_id for c in result.merged.merged_cases}
    assert kept == {"TC_2", "TC_3"}           # TC_1 被 TC_2 吞掉
    assert len(result.merged.dedupe_log) == 1
    entry = result.merged.dedupe_log[0]
    assert entry.kept == "TC_2"
    assert entry.dropped == ["TC_1"]
    assert entry.similarity >= 0.999

    # source_refs 应被合并：TC_2 现在既引用自己的 KP_b 也引用 TC_1 的 KP_a
    winner = next(c for c in result.merged.merged_cases if c.case_id == "TC_2")
    kp_ids = {r.kp_id for r in winner.source_refs}
    assert kp_ids == {"KP_a", "KP_b"}


def test_dedupe_no_duplicates(monkeypatch, tmp_settings):
    c1 = _case("TC_1", title="登录")
    c2 = _case("TC_2", title="注册")
    from backend.agents.case_gen.merger import _case_embed_text
    vecs = {
        _case_embed_text(c1): [1.0, 0.0],
        _case_embed_text(c2): [0.0, 1.0],
    }
    monkeypatch.setattr(merger_mod._emb_mod, "embed", _fake_embed_factory(vecs))

    agent = Merger(project=PROJECT)
    result = agent.run(
        cases=[c1, c2],
        feature_points=[_fp("FP_登录_001")],
        allowed_kp_ids={"KP_登录_br_0001"},
        llm_cfg=_cfg(),
        skip_integration=True,
    )
    assert len(result.merged.merged_cases) == 2
    assert result.merged.dedupe_log == []


def test_dedupe_single_case_shortcut(tmp_settings):
    """只有 1 条用例时不应调用 embedding。"""
    c1 = _case("TC_1")
    # 故意不打桩 embed —— 若被调用会抛错（模型下载失败或类似）
    agent = Merger(project=PROJECT)
    result = agent.run(
        cases=[c1],
        feature_points=[_fp("FP_登录_001")],
        allowed_kp_ids={"KP_登录_br_0001"},
        llm_cfg=_cfg(),
        skip_integration=True,
    )
    assert len(result.merged.merged_cases) == 1
    assert result.merged.dedupe_log == []


def test_dedupe_embedding_failure_fallback(monkeypatch, tmp_settings):
    """embedding 加载报错时，保留全部用例并标 dedupe_skipped=True。"""
    c1 = _case("TC_1")
    c2 = _case("TC_2", title="另一条")

    def boom(texts):
        raise RuntimeError("embedding model unavailable")
    monkeypatch.setattr(merger_mod._emb_mod, "embed", boom)

    agent = Merger(project=PROJECT)
    result = agent.run(
        cases=[c1, c2],
        feature_points=[_fp("FP_登录_001")],
        allowed_kp_ids={"KP_登录_br_0001"},
        llm_cfg=_cfg(),
        skip_integration=True,
    )
    assert result.dedupe_skipped is True
    assert len(result.merged.merged_cases) == 2


# ---- 集成用例（LLM 调用） -------------------------------------------------

def _integration_case_json(case_id: str,
                           fps: list[str],
                           kp: str = "KP_a") -> dict:
    return {
        "case_id": case_id,
        "title": case_id,
        "priority": "P1",
        "category": "正常",
        "feature_point": "FP_集成_001",
        "related_feature_points": fps,
        "preconditions": [],
        "steps": [{"step": 1, "action": "登录", "data": "用户A"}],
        "expected_result": "跳转成功",
        "source_refs": [{"kp_id": kp, "file": "f.md", "section": None}],
        "generated_by": "merger_agent",
        "confidence": 0.6,
        "created_at": "2026-04-28T00:00:00Z",
        "needs_review": True,
    }


def test_integration_happy_path(monkeypatch, tmp_settings):
    c1 = _case("TC_1", fp_id="FP_登录_001", title="登录")
    c2 = _case("TC_2", fp_id="FP_首页_001", title="首页推荐")
    from backend.agents.case_gen.merger import _case_embed_text
    vecs = {
        _case_embed_text(c1): [1.0, 0.0],
        _case_embed_text(c2): [0.0, 1.0],
    }
    monkeypatch.setattr(merger_mod._emb_mod, "embed", _fake_embed_factory(vecs))

    ic = _integration_case_json("TC_集成_0001", ["FP_登录_001", "FP_首页_001"])
    raw = json.dumps({"integration_cases": [ic], "rationale": "补登录→首页"},
                     ensure_ascii=False)
    monkeypatch.setattr(merger_mod._llm_mod, "chat", lambda **kw: raw)

    agent = Merger(project=PROJECT)
    result = agent.run(
        cases=[c1, c2],
        feature_points=[_fp("FP_登录_001"), _fp("FP_首页_001", module="首页")],
        allowed_kp_ids={"KP_登录_br_0001", "KP_a"},
        llm_cfg=_cfg(),
    )
    assert result.llm_calls == 1
    assert result.integration_skipped is False
    assert result.merged.integration_added == ["TC_集成_0001"]
    # 末位新增的一条 case 必为集成用例，并被强制标记
    added = result.merged.merged_cases[-1]
    assert added.generated_by == "merger_agent"
    assert added.needs_review is True
    assert added.confidence <= 0.7


def test_integration_filter_insufficient_related_fps(monkeypatch, tmp_settings):
    """related_feature_points <2 的集成用例必须被丢弃。"""
    c1 = _case("TC_1", fp_id="FP_登录_001")
    from backend.agents.case_gen.merger import _case_embed_text
    vecs = {_case_embed_text(c1): [1.0, 0.0]}
    monkeypatch.setattr(merger_mod._emb_mod, "embed", _fake_embed_factory(vecs))

    bad = _integration_case_json("TC_集成_0001", ["FP_登录_001"])  # 只有 1 个
    raw = json.dumps({"integration_cases": [bad], "rationale": "x"},
                     ensure_ascii=False)
    monkeypatch.setattr(merger_mod._llm_mod, "chat", lambda **kw: raw)

    agent = Merger(project=PROJECT)
    result = agent.run(
        cases=[c1],
        feature_points=[_fp("FP_登录_001")],
        allowed_kp_ids={"KP_登录_br_0001", "KP_a"},
        llm_cfg=_cfg(),
    )
    assert result.merged.integration_added == []
    assert "TC_集成_0001" in result.integration_filtered
    assert result.integration_raw_count == 1


def test_integration_filter_unknown_kp(monkeypatch, tmp_settings):
    """source_refs 指向未在 allowed_kp_ids 里的 kp 必须被丢弃。"""
    c1 = _case("TC_1", fp_id="FP_登录_001")
    c2 = _case("TC_2", fp_id="FP_首页_001")
    from backend.agents.case_gen.merger import _case_embed_text
    vecs = {
        _case_embed_text(c1): [1.0, 0.0],
        _case_embed_text(c2): [0.0, 1.0],
    }
    monkeypatch.setattr(merger_mod._emb_mod, "embed", _fake_embed_factory(vecs))

    bad = _integration_case_json(
        "TC_集成_0001", ["FP_登录_001", "FP_首页_001"], kp="KP_不存在",
    )
    raw = json.dumps({"integration_cases": [bad], "rationale": "x"},
                     ensure_ascii=False)
    monkeypatch.setattr(merger_mod._llm_mod, "chat", lambda **kw: raw)

    agent = Merger(project=PROJECT)
    result = agent.run(
        cases=[c1, c2],
        feature_points=[_fp("FP_登录_001"), _fp("FP_首页_001")],
        allowed_kp_ids={"KP_登录_br_0001"},          # 故意不包含 KP_不存在
        llm_cfg=_cfg(),
    )
    assert result.merged.integration_added == []
    assert "TC_集成_0001" in result.integration_filtered


def test_integration_skipped_flag(monkeypatch, tmp_settings):
    """skip_integration=True 时不应调用 LLM。"""
    c1 = _case("TC_1")
    from backend.agents.case_gen.merger import _case_embed_text
    vecs = {_case_embed_text(c1): [1.0, 0.0]}
    monkeypatch.setattr(merger_mod._emb_mod, "embed", _fake_embed_factory(vecs))

    called = {"n": 0}
    def should_not_be_called(**kw):
        called["n"] += 1
        return "{}"
    monkeypatch.setattr(merger_mod._llm_mod, "chat", should_not_be_called)

    agent = Merger(project=PROJECT)
    result = agent.run(
        cases=[c1],
        feature_points=[_fp("FP_登录_001")],
        allowed_kp_ids={"KP_登录_br_0001"},
        llm_cfg=_cfg(),
        skip_integration=True,
    )
    assert called["n"] == 0
    assert result.integration_skipped is True
    assert result.llm_calls == 0


def test_integration_llm_error_does_not_break_merge(monkeypatch, tmp_settings):
    """LLM 报错时 merged_cases 必须仍保留（来自去重阶段）。"""
    c1 = _case("TC_1")
    c2 = _case("TC_2", title="另一条")
    from backend.agents.case_gen.merger import _case_embed_text
    vecs = {
        _case_embed_text(c1): [1.0, 0.0],
        _case_embed_text(c2): [0.0, 1.0],
    }
    monkeypatch.setattr(merger_mod._emb_mod, "embed", _fake_embed_factory(vecs))

    def boom(**kw):
        raise RuntimeError("api down")
    monkeypatch.setattr(merger_mod._llm_mod, "chat", boom)

    agent = Merger(project=PROJECT)
    result = agent.run(
        cases=[c1, c2],
        feature_points=[_fp("FP_登录_001"), _fp("FP_首页_001")],
        allowed_kp_ids={"KP_登录_br_0001"},
        llm_cfg=_cfg(),
    )
    assert result.integration_skipped is True
    assert result.error is not None
    assert len(result.merged.merged_cases) == 2


def test_empty_cases_input(tmp_settings):
    agent = Merger(project=PROJECT)
    result = agent.run(
        cases=[],
        feature_points=[_fp("FP_登录_001")],
        allowed_kp_ids={"KP_登录_br_0001"},
        llm_cfg=_cfg(),
        skip_integration=True,
    )
    assert result.merged.merged_cases == []
    assert result.merged.dedupe_log == []
