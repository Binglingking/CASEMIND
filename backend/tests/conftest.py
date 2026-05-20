"""pytest 公共 fixture。

约定：
  - PR1 测试尽量不触发 embedding 模型加载（首次加载 ~50MB+）；
    VectorStore 相关测试只验证 meta.jsonl 的向后兼容加载路径，不调 add_chunks。
  - parse_with_schema 测试 monkey-patch 掉 chat()，不发 HTTP。
  - FAISS 不强制依赖；测试默认走 NumPy 回退路径。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_settings(monkeypatch, tmp_path):
    """把 settings 里的关键目录临时指向 tmp_path，保证测试隔离、无残留。"""
    from backend.config import settings

    for attr, sub in [
        ("docs_dir", "docs"),
        ("memory_dir", "memory"),
        ("vector_dir", "vector_store"),
        ("outputs_dir", "outputs"),
        ("prompts_dir", "prompts"),
    ]:
        d = tmp_path / sub
        d.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, attr, d)

    # project_manager 是单例，__init__ 里已把 settings.*_dir 拷到自己的 root_* 字段，
    # 因此 settings 的 monkeypatch 不会生效——必须同时 patch 这些字段。
    from backend.core.project import project_manager
    monkeypatch.setattr(project_manager, "root_docs", tmp_path / "docs")
    monkeypatch.setattr(project_manager, "root_mem", tmp_path / "memory")
    monkeypatch.setattr(project_manager, "root_vec", tmp_path / "vector_store")
    monkeypatch.setattr(project_manager, "root_out", tmp_path / "outputs")

    # FEATURES_STORE_PATH 也要指向临时目录
    from backend import config as cfg_mod
    feat_path = tmp_path / "memory" / "_global" / "features.json"
    feat_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cfg_mod, "FEATURES_STORE_PATH", feat_path)

    # vector_store 模块里的 _paths 使用 settings，所以上面 monkeypatch settings 就够
    yield tmp_path
