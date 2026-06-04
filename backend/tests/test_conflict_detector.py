"""PR6.2：ConflictDetector 单元测试。

策略：
  - stub `embeddings.embed` 用 hash 映射，让控制相似度成为可能
  - stub `llm.chat` 按固定 JSON 返回，不起网络
  - 验证：候选配对、LLM 判断接入、已存在对跳过、模块过滤、孤儿/类型过滤
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from backend.agents import conflict_detector as det_mod
from backend.core import conflict_store, kp_store
from backend.core.llm import LLMConfig
from backend.schemas.conflict import ConflictPair
from backend.schemas.knowledge_point import KnowledgePoint, KPSource


PROJECT = "demo"


def _kp(kp_id: str, content: str, *, module: str = "登录",
        ktype: str = "business_rule", chunk_id: str | None = None,
        orphan: bool = False) -> KnowledgePoint:
    return KnowledgePoint(
        kp_id=kp_id, type=ktype, content=content, module=module,
        source=KPSource(
            file=f"{kp_id}.md",
            chunk_id=chunk_id or f"{kp_id}.md::0::x",
        ),
        doc_version="v1", extracted_at="2026-01-01T00:00:00Z",
        orphan=orphan,
    )


def _cfg() -> LLMConfig:
    # 测试不访问网络；LLMConfig 构造要求 api_key 非空才不会在 chat 抛 RuntimeError，
    # 但我们 monkeypatch 掉了 chat，因此随意字符串即可。
    return LLMConfig(base_url="https://x/v1", api_key="k", model="m")


# ---- fixtures --------------------------------------------------------------

@pytest.fixture
def stub_embed(monkeypatch):
    """content 相同→向量相同（sim=1）；不同→sim ∈ (0, 1) 且稳定可复现。
    用 sha256 的 32 字节当 32 维向量再归一，冲突概率几乎为 0。"""

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


def _judge_json(decisions: list[bool],
                ctype: str = "numeric",
                severity: str = "high",
                description: str = "冲突示例") -> str:
    items = [{
        "is_conflict": b, "type": ctype, "severity": severity,
        "description": description, "evidence": "A vs B",
    } for b in decisions]
    return json.dumps({"items": items}, ensure_ascii=False)


@pytest.fixture
def llm_all_yes(monkeypatch):
    """LLM 判所有候选都冲突。"""
    def chat(messages, cfg, **kw):
        user = messages[1]["content"]
        n = user.count("--- 第 ")
        return _judge_json([True] * max(n, 1))
    monkeypatch.setattr(det_mod._llm_mod, "chat", chat)


@pytest.fixture
def llm_all_no(monkeypatch):
    def chat(messages, cfg, **kw):
        n = messages[1]["content"].count("--- 第 ")
        return _judge_json([False] * max(n, 1))
    monkeypatch.setattr(det_mod._llm_mod, "chat", chat)


# ---- 最小 happy path -------------------------------------------------------

def test_detect_happy_path(tmp_settings, stub_embed, llm_all_yes):
    """同模块两条 KP，content 相似但不相同 → 形成候选 → LLM 判冲突。

    诀窍：stub_embed 对不同 content 返回几乎正交向量，cosine≈0。
    为了制造 sim∈[low, high) 的候选，我们把 sim_low 暂时放宽到 0。
    """
    kp_store.save_all(PROJECT, [
        _kp("KP_登录_br_0001", "最大重试次数为 5 次", chunk_id="a.md::0::x"),
        _kp("KP_登录_br_0002", "最大重试次数为 10 次", chunk_id="b.md::0::y"),
    ])

    det = det_mod.ConflictDetector(PROJECT)
    conflicts, stats = det.detect(_cfg(), sim_low=0.0, sim_high=1.0)
    assert stats.eligible_kps == 2
    assert stats.candidate_pairs == 1
    assert stats.new_conflicts == 1

    loaded = conflict_store.load_all(PROJECT)
    assert len(loaded) == 1
    c = loaded[0]
    # kp_ids 按字典序排列
    assert c.kp_ids == sorted(["KP_登录_br_0001", "KP_登录_br_0002"])
    assert len(c.kp_contents) == 2
    assert c.conflict_id.startswith("cf_demo_")


def test_detect_skips_existing_pair(tmp_settings, stub_embed, llm_all_yes):
    """已在 store 里的 (a,b) 对应被跳过，不重复判。"""
    a = _kp("KP_登录_br_0001", "A", chunk_id="a.md::0::x")
    b = _kp("KP_登录_br_0002", "B", chunk_id="b.md::0::y")
    kp_store.save_all(PROJECT, [a, b])

    # 预置一个冲突
    conflict_store.save_all(PROJECT, [ConflictPair(
        conflict_id="cf_demo_0001",
        kp_ids=sorted([a.kp_id, b.kp_id]),
        type="numeric", severity="high",
        description="老冲突", detected_at="2026-01-01T00:00:00Z",
    )])

    conflicts, stats = det_mod.ConflictDetector(PROJECT).detect(
        _cfg(), sim_low=0.0, sim_high=1.0,
    )
    assert stats.candidate_pairs == 0
    assert stats.new_conflicts == 0


def test_detect_llm_says_no(tmp_settings, stub_embed, llm_all_no):
    """候选产生但 LLM 全判不冲突，store 不新增。"""
    kp_store.save_all(PROJECT, [
        _kp("KP_登录_br_0001", "A", chunk_id="a.md::0::x"),
        _kp("KP_登录_br_0002", "B", chunk_id="b.md::0::y"),
    ])
    _, stats = det_mod.ConflictDetector(PROJECT).detect(
        _cfg(), sim_low=0.0, sim_high=1.0,
    )
    assert stats.candidate_pairs == 1
    assert stats.judged_pairs == 1
    assert stats.new_conflicts == 0
    assert conflict_store.load_all(PROJECT) == []


# ---- 过滤规则 --------------------------------------------------------------

def test_orphan_and_ineligible_types_skipped(tmp_settings, stub_embed, llm_all_yes):
    kp_store.save_all(PROJECT, [
        _kp("KP_x_ac_0001", "孤儿 KP", ktype="acceptance_criteria", orphan=True),
        _kp("KP_x_as_0001", "不参与冲突", ktype="api_spec"),
        _kp("KP_x_df_0001", "数据字段", ktype="data_field"),
    ])
    _, stats = det_mod.ConflictDetector(PROJECT).detect(_cfg(), sim_low=0.0)
    assert stats.eligible_kps == 0
    assert stats.candidate_pairs == 0


def test_module_filter(tmp_settings, stub_embed, llm_all_yes):
    """只处理指定模块。"""
    kp_store.save_all(PROJECT, [
        _kp("KP_登录_br_0001", "A", module="登录", chunk_id="a.md::0::x"),
        _kp("KP_登录_br_0002", "B", module="登录", chunk_id="b.md::0::y"),
        _kp("KP_支付_br_0001", "C", module="支付", chunk_id="c.md::0::z"),
        _kp("KP_支付_br_0002", "D", module="支付", chunk_id="d.md::0::w"),
    ])
    _, stats = det_mod.ConflictDetector(PROJECT).detect(
        _cfg(), sim_low=0.0, sim_high=1.0, modules=["登录"],
    )
    assert stats.eligible_kps == 2
    assert stats.new_conflicts == 1
    # 只有登录模块的那对被记
    loaded = conflict_store.load_all(PROJECT)
    assert all("登录" in kp_id for c in loaded for kp_id in c.kp_ids)


def test_same_chunk_pairs_skipped(tmp_settings, stub_embed, llm_all_yes):
    """同 chunk 内两条 KP 不算冲突候选。"""
    kp_store.save_all(PROJECT, [
        _kp("KP_x_br_0001", "A", chunk_id="same.md::0::x"),
        _kp("KP_x_br_0002", "B", chunk_id="same.md::0::x"),
    ])
    _, stats = det_mod.ConflictDetector(PROJECT).detect(_cfg(), sim_low=0.0)
    assert stats.candidate_pairs == 0


def test_sim_high_filters_near_duplicates(tmp_settings, stub_embed, llm_all_yes):
    """identical content ⇒ sim=1 → 超过 sim_high → 不当候选（视为复述）。"""
    kp_store.save_all(PROJECT, [
        _kp("KP_x_br_0001", "完全一样的内容", chunk_id="a.md::0::x"),
        _kp("KP_x_br_0002", "完全一样的内容", chunk_id="b.md::0::y"),
    ])
    _, stats = det_mod.ConflictDetector(PROJECT).detect(
        _cfg(), sim_low=0.0, sim_high=0.99,
    )
    assert stats.candidate_pairs == 0


# ---- LLM 容错 --------------------------------------------------------------

def test_llm_failure_does_not_crash(tmp_settings, stub_embed, monkeypatch):
    """chat 抛异常 → 跳过本批，detect 不抛。"""
    def boom(*a, **kw):
        raise RuntimeError("network down")
    monkeypatch.setattr(det_mod._llm_mod, "chat", boom)

    kp_store.save_all(PROJECT, [
        _kp("KP_x_br_0001", "A", chunk_id="a.md::0::x"),
        _kp("KP_x_br_0002", "B", chunk_id="b.md::0::y"),
    ])
    conflicts, stats = det_mod.ConflictDetector(PROJECT).detect(
        _cfg(), sim_low=0.0, sim_high=1.0,
    )
    assert stats.candidate_pairs == 1
    assert stats.new_conflicts == 0
    assert conflicts == []
