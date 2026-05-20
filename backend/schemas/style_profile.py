"""团队风格画像（Style Profile）。

由历史用例 + 历史 XMind 聚合产出，用于约束生成阶段的输出风格。
落 memory/<project>/legacy/style_profile.json，由 case_gen / xmind_gen 读取。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CaseStyle(BaseModel):
    """历史用例风格特征。"""
    total_cases: int = 0
    title_scenario_expected_ratio: float = 0.0     # 标题"场景-预期"格式命中率
    avg_steps_per_case: float = 0.0
    avg_expected_per_case: float = 0.0
    steps_expected_aligned_ratio: float = 0.0      # 步骤数 == 预期数 的比例
    stage_distribution: dict[str, float] = Field(default_factory=dict)
    priority_distribution: dict[str, float] = Field(default_factory=dict)
    case_type_distribution: dict[str, float] = Field(default_factory=dict)
    common_assertion_starts: list[str] = Field(default_factory=list)  # 预期首词 Top-K
    common_action_verbs: list[str] = Field(default_factory=list)      # 步骤首词 Top-K


class XMindStyle(BaseModel):
    """历史 XMind 风格特征。"""
    total_trees: int = 0
    total_nodes: int = 0
    avg_depth: float = 0.0
    max_depth: int = 0
    avg_branching: float = 0.0
    leaf_avg_chars: float = 0.0


class StyleProfile(BaseModel):
    """完整团队画像。"""
    project: str
    generated_at: str                              # ISO8601 UTC
    case_style: CaseStyle = Field(default_factory=CaseStyle)
    xmind_style: XMindStyle = Field(default_factory=XMindStyle)
    notes: list[str] = Field(default_factory=list)  # 人类可读说明，注入 prompt
