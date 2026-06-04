"""PR1.3：VectorStore 向后兼容测试。

核心目标：确认旧的 meta.jsonl（无 namespace / version / metadata 字段）
能被新 VectorStore 无报错加载，字段自动补齐默认值。

不触发 embedding 模型加载——只校验反序列化路径。
"""
from __future__ import annotations

import json

import pytest

from backend.core.vector_store import (
    DEFAULT_NAMESPACE,
    INDEX_VERSION,
    StoredChunk,
    VectorStore,
    _paths,
)


def test_stored_chunk_defaults():
    c = StoredChunk(id="x", text="t", source="s", index=0)
    assert c.namespace == DEFAULT_NAMESPACE
    assert c.version == INDEX_VERSION
    assert c.metadata == {}


def test_paths_default_namespace_preserves_legacy_names(tmp_settings):
    """默认 namespace="chunks" 必须沿用旧文件名：<project>.faiss / .meta.jsonl。"""
    idx, npy, meta = _paths("demo", DEFAULT_NAMESPACE)
    assert idx.name == "demo.faiss"
    assert npy.name == "demo.npy"
    assert meta.name == "demo.meta.jsonl"


def test_paths_custom_namespace(tmp_settings):
    idx, npy, meta = _paths("demo", "knowledge_points")
    assert idx.name == "demo.knowledge_points.faiss"
    assert meta.name == "demo.knowledge_points.meta.jsonl"


def test_load_legacy_meta_without_new_fields(tmp_settings):
    """模拟老用户的 meta.jsonl（字段只有 id/text/source/index），加载不报错。"""
    _, _, meta_path = _paths("demo", DEFAULT_NAMESPACE)
    legacy_records = [
        {"id": "login.md::0::0", "text": "登录需要用户名和密码", "source": "login.md", "index": 0},
        {"id": "login.md::1::1", "text": "密码 8~20 位", "source": "login.md", "index": 1},
    ]
    with meta_path.open("w", encoding="utf-8") as f:
        for r in legacy_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    store = VectorStore("demo")   # 默认 namespace
    chunks = store.all_chunks()
    assert len(chunks) == 2
    for c in chunks:
        # 新字段必须被自动补齐
        assert c.namespace == DEFAULT_NAMESPACE
        assert c.version == INDEX_VERSION
        assert c.metadata == {}


def test_load_meta_ignores_unknown_fields(tmp_settings):
    """未来版本可能引入新字段；旧版本加载时应静默忽略，不崩溃。"""
    _, _, meta_path = _paths("demo", DEFAULT_NAMESPACE)
    with meta_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps({
            "id": "x::0::0", "text": "t", "source": "x", "index": 0,
            "future_field_added_in_v2": "some value",
            "another_new_key": {"nested": True},
        }, ensure_ascii=False) + "\n")

    store = VectorStore("demo")
    assert len(store.all_chunks()) == 1


def test_isolated_namespaces(tmp_settings):
    """chunks 与 knowledge_points 两个 namespace 的 meta 文件互不干扰。"""
    _, _, meta_chunks = _paths("demo", DEFAULT_NAMESPACE)
    _, _, meta_kp = _paths("demo", "knowledge_points")
    meta_chunks.write_text(
        json.dumps({"id": "a::0::0", "text": "chunk-A", "source": "a.md", "index": 0}) + "\n",
        encoding="utf-8",
    )
    meta_kp.write_text(
        json.dumps({"id": "kp-1", "text": "密码长度 8~20 位", "source": "a.md",
                    "index": 0, "namespace": "knowledge_points",
                    "metadata": {"module": "登录", "type": "input_constraint"}}) + "\n",
        encoding="utf-8",
    )

    vs_chunks = VectorStore("demo")
    vs_kp = VectorStore("demo", namespace="knowledge_points")
    assert len(vs_chunks.all_chunks()) == 1
    assert len(vs_kp.all_chunks()) == 1
    assert vs_chunks.all_chunks()[0].text == "chunk-A"
    assert vs_kp.all_chunks()[0].metadata["module"] == "登录"
    assert vs_kp.all_chunks()[0].namespace == "knowledge_points"


def test_stats_includes_namespace(tmp_settings):
    store = VectorStore("demo", namespace="knowledge_points")
    s = store.stats()
    assert s["namespace"] == "knowledge_points"
    assert s["chunks"] == 0
