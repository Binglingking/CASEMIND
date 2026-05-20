"""历史 XMind 解析器。

支持：
  - .xmind 原生：zipfile 解包 → content.json（XMind 8/Zen 通用结构）
  - .md 兜底：# 标题层级解析

不解析 marker 字段（团队约定无圆圈数字含义）。

file_id 由调用方传入（来自字节内容 sha1），保证幂等。
"""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path

from backend.core.legacy._hash import file_content_id
from backend.schemas.legacy_xmind import LegacyXMindNode, LegacyXMindTree
from backend.schemas.parse_warning import ParseWarning


# ---- 公共 ----

def _node_id(file_id: str, path_titles: list[str]) -> str:
    raw = (file_id + "::" + " / ".join(path_titles)).encode("utf-8")
    return f"N_{hashlib.sha1(raw).hexdigest()[:10]}"


# ---- .xmind 原生 ----

def _read_xmind_content(path: Path) -> dict | list:
    """优先 content.json（XMind Zen / 2020+），回退 content.xml + 简易解析。"""
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        if "content.json" in names:
            return json.loads(zf.read("content.json").decode("utf-8"))
        if "content.xml" in names:
            raise ValueError(
                "XMIND_OLD_XML_FORMAT: 老版 XMind XML 格式不支持，请另存为新版或导出 .md"
            )
    raise ValueError("无法识别的 .xmind 文件结构（缺少 content.json）")


def _walk_xmind_topic(
    topic: dict,
    file_id: str,
    parent_path: list[str],
    parent_id: str | None,
    out: list[LegacyXMindNode],
    depth: int,
) -> str:
    title = (topic.get("title") or "").strip() or "(空节点)"
    full_path = parent_path + [title]
    nid = _node_id(file_id, full_path)

    children_block = topic.get("children") or {}
    raw_children = []
    if isinstance(children_block, dict):
        for v in children_block.values():
            if isinstance(v, list):
                raw_children.extend(v)
    elif isinstance(children_block, list):
        raw_children = children_block

    note = ""
    notes = topic.get("notes")
    if isinstance(notes, dict):
        plain = notes.get("plain") or {}
        if isinstance(plain, dict):
            note = (plain.get("content") or "").strip()

    child_ids: list[str] = []
    for child in raw_children:
        if isinstance(child, dict):
            cid = _walk_xmind_topic(child, file_id, full_path, nid, out, depth + 1)
            child_ids.append(cid)

    out.append(LegacyXMindNode(
        node_id=nid,
        title=title,
        depth=depth,
        path=full_path,
        parent_id=parent_id,
        children_ids=child_ids,
        is_leaf=not child_ids,
        note=note,
    ))
    return nid


def parse_xmind(path: Path, file_id: str | None = None) -> LegacyXMindTree:
    from backend.core.timeutil import utc_iso_z

    raw = _read_xmind_content(path)
    # XMind Zen content.json 是 list[sheet]；取第一个 sheet 的 rootTopic
    sheets: list[dict] = raw if isinstance(raw, list) else [raw]
    if not sheets:
        raise ValueError(".xmind 文件不含任何 sheet")
    root_topic = sheets[0].get("rootTopic") if isinstance(sheets[0], dict) else None
    if not isinstance(root_topic, dict):
        raise ValueError(".xmind 文件不含 rootTopic")

    fid = file_id or file_content_id(path)
    nodes: list[LegacyXMindNode] = []
    root_id = _walk_xmind_topic(root_topic, fid, [], None, nodes, 0)

    st = path.stat()
    return LegacyXMindTree(
        file_id=fid,
        name=path.name,
        ext=path.suffix.lower(),
        size=int(st.st_size),
        mtime=float(st.st_mtime),
        uploaded_at=utc_iso_z(),
        root_id=root_id,
        nodes=nodes,
        parse_warnings=[],
    )


# ---- .md 兜底 ----

_MD_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_MD_LIST_RE = re.compile(r"^(\s*)[-*+]\s+(.+?)\s*$")


def parse_xmind_md(path: Path, file_id: str | None = None) -> LegacyXMindTree:
    """从 Markdown 解析层级树。

    支持两种语法：
      - `#`/`##`/`###` 层级
      - `-` / `*` 缩进列表
    两者可混用：先按 # 切顶层节，再在每节内按列表缩进展开子节点。
    """
    from backend.core.timeutil import utc_iso_z

    text = path.read_text(encoding="utf-8", errors="ignore")
    file_id = file_id or file_content_id(path)
    warnings: list[ParseWarning] = []

    root_path = [path.stem or "root"]
    root_id = _node_id(file_id, root_path)

    # 中间结构：{node_id: dict}
    raw: dict[str, dict] = {
        root_id: {
            "node_id": root_id, "title": root_path[0], "depth": 0,
            "path": root_path, "parent_id": None,
            "children_ids": [], "note": "",
        }
    }
    order: list[str] = [root_id]
    # parent_child_map: parent_id -> list[child_id] in insertion order
    parent_to_children: dict[str, list[str]] = {root_id: []}
    # 解析栈：(depth, node_id, path_titles)
    stack: list[tuple[int, str, list[str]]] = [(0, root_id, root_path)]

    def add_node(depth: int, title: str):
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if not stack:
            warnings.append(ParseWarning(
                level="warning", code="INVALID_DEPTH_JUMP",
                message=f"层级异常：{title!r} 在第一行就深于根，强制接到根",
                node_path=[title],
            ))
            stack.append((0, root_id, root_path))
        parent_depth, parent_id, parent_path = stack[-1]
        full_path = parent_path + [title]
        nid = _node_id(file_id, full_path)
        if nid in raw:
            warnings.append(ParseWarning(
                level="warning", code="DUPLICATE_NODE_PATH",
                message=f"重复节点路径：{' / '.join(full_path)}",
                node_path=list(full_path),
            ))
            return
        raw[nid] = {
            "node_id": nid, "title": title, "depth": depth,
            "path": full_path, "parent_id": parent_id,
            "children_ids": [], "note": "",
        }
        parent_to_children.setdefault(parent_id, []).append(nid)
        parent_to_children.setdefault(nid, [])
        order.append(nid)
        stack.append((depth, nid, full_path))

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        m = _MD_HEADER_RE.match(line)
        if m:
            depth = len(m.group(1))
            title = m.group(2).strip()
            add_node(depth, title)
            continue

        m = _MD_LIST_RE.match(line)
        if m:
            indent = len(m.group(1).expandtabs(4))
            title = m.group(2).strip()
            current_top_depth = stack[-1][0] if stack else 0
            list_depth = max(current_top_depth + 1, 1 + indent // 2)
            add_node(list_depth, title)
            continue

    nodes: list[LegacyXMindNode] = []
    for nid in order:
        d = raw[nid]
        children = parent_to_children.get(nid, [])
        nodes.append(LegacyXMindNode(
            node_id=d["node_id"],
            title=d["title"],
            depth=d["depth"],
            path=d["path"],
            parent_id=d["parent_id"],
            children_ids=list(children),
            is_leaf=not children,
            note=d["note"],
        ))

    st = path.stat()
    return LegacyXMindTree(
        file_id=file_id,
        name=path.name,
        ext=path.suffix.lower(),
        size=int(st.st_size),
        mtime=float(st.st_mtime),
        uploaded_at=utc_iso_z(),
        root_id=root_id,
        nodes=nodes,
        parse_warnings=warnings,
    )


def parse_any(path: Path, file_id: str | None = None) -> LegacyXMindTree:
    """根据扩展名分发。"""
    ext = path.suffix.lower()
    if ext == ".xmind":
        return parse_xmind(path, file_id=file_id)
    if ext in (".md", ".markdown"):
        return parse_xmind_md(path, file_id=file_id)
    raise ValueError(f"不支持的 XMind 资产格式：{ext}")
