"""历史 XMind 解析器测试。

.xmind 测试用 zipfile + content.json 手工构造，避免依赖外部样例文件。
.md 测试用临时文件。
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from backend.core.legacy.xmind_parser import (
    parse_any,
    parse_xmind,
    parse_xmind_md,
)


# ---- .xmind 原生 ----

def _make_xmind(path: Path, root_topic: dict) -> None:
    content = [{"id": "sheet1", "title": "Sheet 1", "rootTopic": root_topic}]
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("content.json", json.dumps(content, ensure_ascii=False))
        zf.writestr("metadata.json", "{}")


def test_parse_xmind_simple_tree(tmp_path):
    root = {
        "title": "支付模块",
        "children": {"attached": [
            {"title": "下单页", "children": {"attached": [
                {"title": "金额校验", "children": {"attached": [
                    {"title": "金额>0"},
                    {"title": "金额<=99999"},
                ]}},
            ]}},
        ]},
    }
    p = tmp_path / "pay.xmind"
    _make_xmind(p, root)

    tree = parse_xmind(p)
    titles = {n.title for n in tree.nodes}
    assert "支付模块" in titles
    assert "金额>0" in titles

    leaves = tree.leaves()
    leaf_titles = {n.title for n in leaves}
    assert leaf_titles == {"金额>0", "金额<=99999"}

    # 路径正确
    leaf = next(n for n in leaves if n.title == "金额>0")
    assert leaf.path == ["支付模块", "下单页", "金额校验", "金额>0"]
    assert leaf.depth == 3

    # 父子关系互相引用
    by_id = tree.by_id()
    assert leaf.parent_id is not None
    parent = by_id[leaf.parent_id]
    assert leaf.node_id in parent.children_ids


def test_parse_xmind_notes_extraction(tmp_path):
    root = {
        "title": "根",
        "notes": {"plain": {"content": "根备注"}},
        "children": {"attached": [
            {"title": "子", "notes": {"plain": {"content": "子备注"}}},
        ]},
    }
    p = tmp_path / "n.xmind"
    _make_xmind(p, root)
    tree = parse_xmind(p)
    by_t = {n.title: n for n in tree.nodes}
    assert by_t["根"].note == "根备注"
    assert by_t["子"].note == "子备注"


def test_parse_xmind_missing_content_json_errors(tmp_path):
    p = tmp_path / "bad.xmind"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("metadata.json", "{}")
    with pytest.raises(ValueError):
        parse_xmind(p)


# ---- .md 兜底 ----

def test_parse_xmind_md_headers(tmp_path):
    md = (
        "# 支付模块\n"
        "## 下单页\n"
        "### 金额校验\n"
        "#### 金额>0\n"
        "#### 金额<=99999\n"
        "## 支付结果页\n"
        "### 成功提示\n"
    )
    p = tmp_path / "x.md"
    p.write_text(md, encoding="utf-8")
    tree = parse_xmind_md(p)
    titles = [n.title for n in tree.nodes]
    assert "支付模块" in titles
    assert "金额>0" in titles
    leaves = {n.title for n in tree.leaves()}
    assert "金额>0" in leaves
    assert "成功提示" in leaves
    # 中间节点不应是叶子
    by_t = {n.title: n for n in tree.nodes}
    assert not by_t["金额校验"].is_leaf


def test_parse_xmind_md_list_indented(tmp_path):
    md = (
        "# 登录\n"
        "- 账号登录\n"
        "  - 账号正确\n"
        "  - 账号错误\n"
        "- 短信登录\n"
    )
    p = tmp_path / "x.md"
    p.write_text(md, encoding="utf-8")
    tree = parse_xmind_md(p)
    titles = [n.title for n in tree.nodes]
    for t in ["登录", "账号登录", "账号正确", "账号错误", "短信登录"]:
        assert t in titles


def test_parse_any_dispatch(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("# A\n## B\n", encoding="utf-8")
    t = parse_any(p)
    assert any(n.title == "A" for n in t.nodes)

    with pytest.raises(ValueError):
        parse_any(tmp_path / "x.docx")
