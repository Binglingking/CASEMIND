"""Stage 1：归一化。

读 legacy_store 已落盘的 cases / xmind 树 → 产出 NormalizedBatch。
纯函数，无 LLM。
"""
from __future__ import annotations

from backend.agents.legacy_analyzer.schemas import (
    NormalizedBatch,
    NormalizedCaseUnit,
    NormalizedXMindLeaf,
)
from backend.core.legacy import legacy_store
from backend.schemas.legacy_case import LegacyCase
from backend.schemas.legacy_xmind import LegacyXMindNode, LegacyXMindTree


# 中间层节点入向量库的最小深度阈值（避免根节点污染语义）
MID_DEPTH_MIN = 2
# 同一层兄弟节点采样上限，防 prompt 爆炸
MAX_SIBLINGS = 6


def _to_case_unit(c: LegacyCase) -> NormalizedCaseUnit:
    pairs: list[tuple[str, str]] = []
    for s in c.steps:
        pairs.append((
            (s.action or "").strip(),
            (s.expected or "").strip(),
        ))
    return NormalizedCaseUnit(
        case_id=c.case_id,
        file_id=c.case_id.split("_")[1] if c.case_id.startswith("LC_") else "",
        source_file=c.source_file,
        source_row=c.source_row,
        suite=(c.suite or "").strip(),
        module=(c.module or "").strip(),
        sub_item_base=(c.sub_item_base or "").strip(),
        stage=(c.stage or "").strip(),
        title=(c.title or "").strip(),
        preconditions=(c.preconditions or "").strip(),
        step_pairs=pairs,
        priority=(c.priority or "").strip(),
        case_type=(c.case_type or "").strip(),
    )


def _siblings_of(
    node: LegacyXMindNode,
    by_id: dict[str, LegacyXMindNode],
) -> list[str]:
    if not node.parent_id or node.parent_id not in by_id:
        return []
    parent = by_id[node.parent_id]
    sibs = [
        by_id[cid].title
        for cid in parent.children_ids
        if cid in by_id and cid != node.node_id
    ]
    return sibs[:MAX_SIBLINGS]


def _to_leaf(node: LegacyXMindNode, tree: LegacyXMindTree) -> NormalizedXMindLeaf:
    by_id = tree.by_id()
    return NormalizedXMindLeaf(
        node_id=node.node_id,
        file_id=tree.file_id,
        source_file=tree.name,
        title=node.title,
        path=list(node.path),
        siblings=_siblings_of(node, by_id),
        note=node.note or "",
    )


def normalize(project: str) -> NormalizedBatch:
    """读取项目所有已解析的历史资产并归一化。"""
    case_units: list[NormalizedCaseUnit] = []
    for c in legacy_store.all_cases(project):
        case_units.append(_to_case_unit(c))

    leaves: list[NormalizedXMindLeaf] = []
    mid_nodes: list[NormalizedXMindLeaf] = []
    for f in legacy_store.list_xmind_files(project):
        tree = legacy_store.load_xmind_tree(project, f.get("file_id", ""))
        if tree is None:
            continue
        for n in tree.nodes:
            if n.is_leaf:
                leaves.append(_to_leaf(n, tree))
            elif n.depth >= MID_DEPTH_MIN:
                mid_nodes.append(_to_leaf(n, tree))

    return NormalizedBatch(
        project=project,
        case_units=case_units,
        xmind_leaves=leaves,
        xmind_mid_nodes=mid_nodes,
    )
