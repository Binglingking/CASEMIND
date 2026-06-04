"""legacy_analyzer 内部 Schema：Stage 2 LLM 输出 + 各 Stage 间数据对象。"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from backend.schemas.knowledge_point import KPType


SourceKind = Literal["case", "xmind"]


# ---------- Stage 1：归一化输入单元 ----------

class NormalizedCaseUnit(BaseModel):
    """单条用例归一化后供 Stage 2 消费的单元。

    与 LegacyCase 的差异：模块/子项做了空值填充与 trim；steps 摊平成纯文本对供 prompt 使用。
    """
    case_id: str
    file_id: str
    source_file: str
    source_row: int
    suite: str
    module: str
    sub_item_base: str
    stage: str
    title: str
    preconditions: str
    step_pairs: list[tuple[str, str]] = Field(default_factory=list)
    priority: str
    case_type: str


class NormalizedXMindLeaf(BaseModel):
    """XMind 叶子节点（含完整路径）+ 关键中间层节点供 Stage 2 消费。"""
    node_id: str
    file_id: str
    source_file: str
    title: str
    path: list[str]
    siblings: list[str] = Field(default_factory=list)
    note: str = ""


class NormalizedBatch(BaseModel):
    """Stage 1 完整产出，作为后续四阶段的输入。"""
    project: str
    case_units: list[NormalizedCaseUnit] = Field(default_factory=list)
    xmind_leaves: list[NormalizedXMindLeaf] = Field(default_factory=list)
    xmind_mid_nodes: list[NormalizedXMindLeaf] = Field(default_factory=list)


# ---------- Stage 2：信号抽取 LLM 输出 ----------

class ExtractedSignal(BaseModel):
    """LLM 单条输出。source_kind / source_ref 由 prompt 强约束 LLM 必填。"""
    type: KPType
    content: str = Field(..., max_length=300)
    module: str
    aliases: list[str] = Field(default_factory=list, max_length=5)
    source_kind: SourceKind
    source_ref: str                  # case_id 或 node_id
    confidence: float = 0.7
    reasoning: str = ""              # 推理依据（可见审核时帮判断）


class ExtractBatchOutput(BaseModel):
    """Stage 2 单批 LLM 调用输出。"""
    items: list[ExtractedSignal] = Field(default_factory=list)


# ---------- Stage 3：风格统计中间值 ----------

class StyleStats(BaseModel):
    """聚合层用，结构与 StyleProfile 接近但不含 project / generated_at。"""
    title_scenario_expected_ratio: float = 0.0
    avg_steps_per_case: float = 0.0
    avg_expected_per_case: float = 0.0
    steps_expected_aligned_ratio: float = 0.0
    stage_distribution: dict[str, float] = Field(default_factory=dict)
    priority_distribution: dict[str, float] = Field(default_factory=dict)
    case_type_distribution: dict[str, float] = Field(default_factory=dict)
    common_assertion_starts: list[str] = Field(default_factory=list)
    common_action_verbs: list[str] = Field(default_factory=list)
    total_cases: int = 0
    total_trees: int = 0
    total_nodes: int = 0
    avg_depth: float = 0.0
    max_depth: int = 0
    avg_branching: float = 0.0
    leaf_avg_chars: float = 0.0


# ---------- Stage 4：聚合后输出 ----------

class AggregatedSignals(BaseModel):
    """Stage 4 输出。"""
    items: list[ExtractedSignal] = Field(default_factory=list)
    by_module: dict[str, list[str]] = Field(default_factory=dict)   # module -> [content...]
    duplicates_dropped: int = 0


# ---------- 总输出 ----------

class AnalyzerRunResult(BaseModel):
    """runner.run 的最终返回。"""
    project: str
    case_units_count: int
    xmind_leaves_count: int
    xmind_mid_count: int
    llm_calls: int
    extracted_count: int
    aggregated_count: int
    style_stats: StyleStats
    inferred_count: int
    pending_review_count: int = 0
    ready_to_build_count: int = 0
    file_summary_count: int = 0
    errors: list[str] = Field(default_factory=list)
