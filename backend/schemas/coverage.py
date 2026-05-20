"""覆盖率度量数据模型。详见 docs/design/04_coverage_metric.md。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


CoverageStrength = Literal["strong", "medium", "weak", "uncovered"]


class CoverageMatch(BaseModel):
    """KP 被某条 case 覆盖的命中记录。"""
    case_id: str
    match: Literal["explicit", "same_chunk", "semantic"]
    similarity: float = 0.0          # 仅 semantic 时有意义


class KPCoverage(BaseModel):
    kp_id: str
    strength: float                  # [0, 1.0]
    strength_level: CoverageStrength
    covered_by: list[CoverageMatch] = Field(default_factory=list)
    # 冗余字段方便前端渲染，不需要回查 knowledge_points.json
    kp_module: str
    kp_type: str
    kp_content_preview: str = Field("", max_length=120)


class CoverageReport(BaseModel):
    pipeline_id: str
    project: str
    generated_at: str
    total_kps: int
    total_cases: int
    strict_coverage: float           # 仅显式引用
    weighted_coverage: float         # 含语义相似加权
    by_module: dict[str, float] = Field(default_factory=dict)
    by_type: dict[str, float] = Field(default_factory=dict)
    by_priority: dict[str, float] = Field(default_factory=dict)
    weakest_modules: list[str] = Field(default_factory=list)
    uncovered_kps: list[KPCoverage] = Field(default_factory=list)
    weak_kps: list[KPCoverage] = Field(default_factory=list)
    details: list[KPCoverage] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
