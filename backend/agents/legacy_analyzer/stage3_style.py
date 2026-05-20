"""Stage 3：风格特征提取（纯函数）。

历史用例：标题"场景-预期"匹配率、平均步骤数、断言首词分布、阶段分布、优先级分布
历史 XMind：层级深度、扇出、叶子粒度
"""
from __future__ import annotations

import re
from collections import Counter

from backend.agents.legacy_analyzer.schemas import NormalizedBatch, StyleStats
from backend.core.legacy import legacy_store


# 标题"场景-预期"判定：用 - 或 — 或 _ 作分隔的两段式
_TITLE_SCENARIO_RE = re.compile(r"^.+?[-—_].+$")
_VERB_HEAD_RE = re.compile(r"^(\S+?)[ 　，,。.：:]")

TOP_K_HEADS = 8


def _ratio(n: int, total: int) -> float:
    return (n / total) if total else 0.0


def _distribution(items: list[str]) -> dict[str, float]:
    if not items:
        return {}
    total = len(items)
    c = Counter(items)
    return {k: round(v / total, 4) for k, v in c.items()}


def _top_heads(texts: list[str], k: int = TOP_K_HEADS) -> list[str]:
    heads: list[str] = []
    for t in texts:
        s = (t or "").strip()
        if not s:
            continue
        m = _VERB_HEAD_RE.match(s)
        head = m.group(1) if m else s.split()[0]
        if 1 <= len(head) <= 6:
            heads.append(head)
    if not heads:
        return []
    return [w for w, _ in Counter(heads).most_common(k)]


def compute_style(project: str, batch: NormalizedBatch) -> StyleStats:
    cases = batch.case_units
    total_cases = len(cases)

    title_match = sum(1 for c in cases if _TITLE_SCENARIO_RE.match(c.title or ""))
    steps_lens = [len(c.step_pairs) for c in cases]
    expected_lens = [
        sum(1 for _, e in c.step_pairs if e) for c in cases
    ]
    aligned = sum(
        1 for c in cases
        if c.step_pairs and len(c.step_pairs) == sum(1 for _, e in c.step_pairs if e)
    )
    stages = [c.stage for c in cases if c.stage]
    priorities = [c.priority for c in cases if c.priority]
    case_types = [c.case_type for c in cases if c.case_type]

    action_texts: list[str] = []
    expected_texts: list[str] = []
    for c in cases:
        for a, e in c.step_pairs:
            if a:
                action_texts.append(a)
            if e:
                expected_texts.append(e)

    # XMind 层级 / 扇出 / 叶子粒度需要原始 tree
    total_trees = 0
    total_nodes = 0
    depths: list[int] = []
    branching: list[int] = []
    leaf_chars: list[int] = []
    max_depth = 0
    for f in legacy_store.list_xmind_files(project):
        tree = legacy_store.load_xmind_tree(project, f.get("file_id", ""))
        if tree is None:
            continue
        total_trees += 1
        total_nodes += len(tree.nodes)
        for n in tree.nodes:
            depths.append(n.depth)
            if n.depth > max_depth:
                max_depth = n.depth
            if not n.is_leaf:
                branching.append(len(n.children_ids))
            else:
                leaf_chars.append(len(n.title or ""))

    avg = lambda xs: round(sum(xs) / len(xs), 3) if xs else 0.0

    return StyleStats(
        title_scenario_expected_ratio=round(_ratio(title_match, total_cases), 4),
        avg_steps_per_case=avg(steps_lens),
        avg_expected_per_case=avg(expected_lens),
        steps_expected_aligned_ratio=round(_ratio(aligned, total_cases), 4),
        stage_distribution=_distribution(stages),
        priority_distribution=_distribution(priorities),
        case_type_distribution=_distribution(case_types),
        common_assertion_starts=_top_heads(expected_texts),
        common_action_verbs=_top_heads(action_texts),
        total_cases=total_cases,
        total_trees=total_trees,
        total_nodes=total_nodes,
        avg_depth=avg(depths),
        max_depth=max_depth,
        avg_branching=avg(branching),
        leaf_avg_chars=avg(leaf_chars),
    )
