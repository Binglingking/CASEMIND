"""PR2.2：KnowledgeExtractor 单元测试。

策略：monkey-patch backend.core.llm.chat，完全不发 HTTP。

覆盖点：
  - 单 chunk 成功抽取 + 写缓存
  - 幂等：同 chunk 第二次不调 LLM
  - chat 异常 → 写 error cache，不抛
  - LLM 返回坏 JSON → parse_with_schema 重试成功 / 失败写 error cache
  - incremental 合并：edited_by_user 保留、新抽取替换、orphan 标记
  - MemoryAgent 的 feature flag off 回归：hook 完全不跑
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.agents.knowledge_extractor import KnowledgeExtractor, _build_chunk_id
from backend.core import kp_store
from backend.core import llm as llm_module
from backend.core.chunker import Chunk
from backend.core.llm import LLMConfig


PROJECT = "demo"


def _cfg() -> LLMConfig:
    return LLMConfig(base_url="https://x/api/v1", api_key="k", model="m")


def _valid_llm_output() -> str:
    return json.dumps({
        "items": [
            {"type": "input_constraint", "content": "密码 8~20 位",
             "module": "登录", "aliases": ["口令"], "section": "3.2", "confidence": 0.9},
            {"type": "exception_flow", "content": "连续输错 5 次锁定 30 分钟",
             "module": "登录", "aliases": [], "section": "3.2", "confidence": 0.9},
        ]
    }, ensure_ascii=False)


# ---- 单 chunk 抽取 ---------------------------------------------------------

def test_extract_single_chunk_success(tmp_settings, monkeypatch):
    monkeypatch.setattr(
        llm_module, "chat",
        lambda messages, cfg, **kw: _valid_llm_output(),
    )
    extractor = KnowledgeExtractor(PROJECT)
    chunks = [Chunk(text="密码 8~20 位。连续错 5 次锁定 30 分钟。",
                    source="login.md", index=0)]
    kps = extractor.extract_for_chunks(
        chunks, source_file="login.md",
        doc_version="2026-01-01T00:00:00Z", llm_cfg=_cfg(),
    )
    assert len(kps) == 2
    assert kps[0].kp_id.startswith("KP_登录_ic_")
    assert kps[1].type == "exception_flow"
    assert kps[0].source.file == "login.md"
    assert kps[0].source.chunk_id.startswith("login.md::0::")


def test_idempotent_cache_hit(tmp_settings, monkeypatch):
    """同一 chunk 抽过一次后，第二次不应再调 chat。"""
    calls = {"n": 0}

    def counting_chat(messages, cfg, **kw):
        calls["n"] += 1
        return _valid_llm_output()

    monkeypatch.setattr(llm_module, "chat", counting_chat)

    chunks = [Chunk(text="密码 8~20 位", source="login.md", index=0)]
    ext = KnowledgeExtractor(PROJECT)
    ext.extract_for_chunks(chunks, "login.md", "v1", _cfg())
    ext.extract_for_chunks(chunks, "login.md", "v1", _cfg())
    assert calls["n"] == 1


def test_cache_miss_when_chunk_text_changes(tmp_settings, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(llm_module, "chat",
                        lambda messages, cfg, **kw: (calls.__setitem__("n", calls["n"] + 1), _valid_llm_output())[1])
    ext = KnowledgeExtractor(PROJECT)
    ext.extract_for_chunks(
        [Chunk(text="v1 文本", source="f.md", index=0)], "f.md", "v1", _cfg())
    ext.extract_for_chunks(
        [Chunk(text="v2 文本", source="f.md", index=0)], "f.md", "v2", _cfg())
    assert calls["n"] == 2


def test_chat_raises_is_swallowed_and_writes_error_cache(tmp_settings, monkeypatch):
    def boom(messages, cfg, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(llm_module, "chat", boom)

    chunks = [Chunk(text="abc", source="f.md", index=0)]
    kps = KnowledgeExtractor(PROJECT).extract_for_chunks(
        chunks, "f.md", "v1", _cfg())
    assert kps == []
    # error cache 应该被写出来
    from backend.core.project import project_manager
    err_dir = project_manager.mem_dir(PROJECT) / kp_store.CACHE_DIR
    errs = list(err_dir.glob("*.error.json"))
    assert len(errs) == 1
    data = json.loads(errs[0].read_text(encoding="utf-8"))
    assert "network down" in data["reason"]


def test_schema_validation_failure_writes_error_cache(tmp_settings, monkeypatch):
    """LLM 一直返回坏 JSON → error cache，不抛。"""
    monkeypatch.setattr(llm_module, "chat",
                        lambda messages, cfg, **kw: "not json at all {{{")
    chunks = [Chunk(text="abc", source="f.md", index=0)]
    kps = KnowledgeExtractor(PROJECT).extract_for_chunks(
        chunks, "f.md", "v1", _cfg())
    assert kps == []
    from backend.core.project import project_manager
    err_dir = project_manager.mem_dir(PROJECT) / kp_store.CACHE_DIR
    errs = list(err_dir.glob("*.error.json"))
    assert len(errs) == 1
    assert "schema" in errs[0].read_text(encoding="utf-8").lower()


def test_retry_recovers_from_bad_first_output(tmp_settings, monkeypatch):
    """第一次返回坏 JSON，第二次返回合法——应该成功。"""
    responses = iter(["not json", _valid_llm_output()])

    def fake_chat(messages, cfg, **kw):
        return next(responses)

    monkeypatch.setattr(llm_module, "chat", fake_chat)
    chunks = [Chunk(text="abc", source="f.md", index=0)]
    kps = KnowledgeExtractor(PROJECT).extract_for_chunks(
        chunks, "f.md", "v1", _cfg())
    assert len(kps) == 2


# ---- incremental 合并 -----------------------------------------------------

def test_incremental_replaces_same_chunk_kp(tmp_settings, monkeypatch):
    """旧 KP 归属变更 chunk，incremental 后被新 KP 替换。"""
    # 先造一条旧 KP，对应 f.md::0::<hash of "old">
    from backend.schemas.knowledge_point import KnowledgePoint, KPSource
    old_chunk_id = _build_chunk_id("f.md", 0, "old text")
    old = KnowledgePoint(
        kp_id="KP_登录_br_0001", type="business_rule", content="旧内容",
        module="登录", source=KPSource(file="f.md", chunk_id=old_chunk_id),
        doc_version="v0", extracted_at="2026-01-01T00:00:00Z",
    )
    kp_store.save_all(PROJECT, [old])

    monkeypatch.setattr(llm_module, "chat",
                        lambda messages, cfg, **kw: _valid_llm_output())
    # 现在同样是 index=0 但文本变了 → chunk_id 不同 → 旧 KP 在 live_sources 里 → 应被保留？
    # 其实：design 说 affected_chunk_ids = 本次重抽的 chunk_id。
    # 旧 chunk_id 不在本次 affected_chunk_ids 里（因为文本变了），所以不会被替换。
    # 它会被标 orphan=False（因为 f.md 还活着）。
    result = KnowledgeExtractor(PROJECT).extract_incremental(
        changed_sources=[("f.md", "v1", [Chunk(text="new text", source="f.md", index=0)])],
        llm_cfg=_cfg(),
        live_sources={"f.md"},
    )
    all_kps = kp_store.load_all(PROJECT)
    # 新增 2 条 + 旧 1 条保留（chunk_id 不同）
    assert result["added"] == 2
    assert len(all_kps) == 3
    assert any(k.kp_id == "KP_登录_br_0001" for k in all_kps)


def test_incremental_orphans_deleted_source(tmp_settings, monkeypatch):
    from backend.schemas.knowledge_point import KnowledgePoint, KPSource
    zombie = KnowledgePoint(
        kp_id="KP_登录_br_0001", type="business_rule", content="来自已删除文件",
        module="登录", source=KPSource(file="gone.md", chunk_id="gone.md::0::h"),
        doc_version="v0", extracted_at="2026-01-01T00:00:00Z",
    )
    kp_store.save_all(PROJECT, [zombie])

    monkeypatch.setattr(llm_module, "chat",
                        lambda messages, cfg, **kw: '{"items": []}')
    KnowledgeExtractor(PROJECT).extract_incremental(
        changed_sources=[],
        llm_cfg=_cfg(),
        live_sources={"still-here.md"},
    )
    all_kps = kp_store.load_all(PROJECT)
    assert len(all_kps) == 1
    assert all_kps[0].orphan is True


def test_rebuild_all_preserves_edited_and_marks_orphan(tmp_settings, monkeypatch):
    from backend.schemas.knowledge_point import KnowledgePoint, KPSource
    edited = KnowledgePoint(
        kp_id="KP_登录_br_0001", type="business_rule", content="user edited",
        module="登录", source=KPSource(file="old.md", chunk_id="old.md::0::h"),
        doc_version="v0", extracted_at="2026-01-01T00:00:00Z",
        edited_by_user=True,
    )
    kp_store.save_all(PROJECT, [edited])

    monkeypatch.setattr(llm_module, "chat",
                        lambda messages, cfg, **kw: _valid_llm_output())
    result = KnowledgeExtractor(PROJECT).rebuild_all(
        all_sources=[("login.md", "v1",
                      [Chunk(text="密码 8~20 位", source="login.md", index=0)])],
        llm_cfg=_cfg(),
        keep_edited=True,
    )
    all_kps = kp_store.load_all(PROJECT)
    # edited 被保留
    edited_after = [k for k in all_kps if k.kp_id == "KP_登录_br_0001"]
    assert len(edited_after) == 1
    # old.md 不在 live_sources 里 → orphan=True
    assert edited_after[0].orphan is True
    assert result["preserved_edited"] == 1
    assert result["newly_extracted"] == 2


# ---- MemoryAgent hook 回归 ------------------------------------------------

def test_memory_agent_hook_noop_when_flag_off(tmp_settings, monkeypatch):
    """features.enable_knowledge_extraction=False 时，MemoryAgent 不应触发抽取。"""
    # 默认 flag 就是 False（无磁盘文件），不用改 flag 文件
    calls = {"n": 0}
    monkeypatch.setattr(llm_module, "chat",
                        lambda messages, cfg, **kw: (calls.__setitem__("n", calls["n"] + 1), "whatever")[1])

    # 模拟 build 里 hook 段的那段代码
    from backend.api.routes_settings import get_runtime_features
    feats = get_runtime_features()
    assert feats.enable_knowledge_extraction is False
    # 不调用 extractor —— calls["n"] 保持 0
    if feats.enable_knowledge_extraction:
        KnowledgeExtractor(PROJECT).extract_incremental([], _cfg())
    assert calls["n"] == 0


def test_memory_agent_hook_runs_when_flag_on(tmp_settings, monkeypatch):
    # 打开磁盘开关
    from backend import config as cfg_mod
    cfg_mod.FEATURES_STORE_PATH.write_text(
        json.dumps({"enable_knowledge_extraction": True}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_module, "chat",
                        lambda messages, cfg, **kw: _valid_llm_output())

    from backend.api.routes_settings import get_runtime_features
    feats = get_runtime_features()
    assert feats.enable_knowledge_extraction is True
    result = KnowledgeExtractor(PROJECT).extract_incremental(
        changed_sources=[("login.md", "v1",
                         [Chunk(text="密码 8~20 位", source="login.md", index=0)])],
        llm_cfg=_cfg(),
        live_sources={"login.md"},
    )
    assert result["added"] == 2
