"""功能点（Feature Point）数据模型 + 切片 Agent 输出。

Step 1 需求切片 Agent 的输出结构。
详见 docs/design/03_case_gen_pipeline.md §5。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Priority = Literal["P0", "P1", "P2", "P3"]


class FeaturePoint(BaseModel):
    fp_id: str                       # FP_<module>_<seq:03d>
    name: str = Field(..., max_length=30)
    description: str = Field(..., max_length=400)  # 软目标 200 字，硬顶 400 留余地
    module: str
    related_kp_ids: list[str] = Field(default_factory=list)
    related_chunk_ids: list[str] = Field(default_factory=list)
    priority: Priority = "P1"
    user_edited: bool = False


class CoverageSelfCheck(BaseModel):
    """LLM 在 Step 1 做的自检——必须输出，后端还要二次校验不能光信 LLM。"""
    total_kps_input: int
    kps_covered_by_feature_points: int
    uncovered_kp_ids: list[str] = Field(default_factory=list)


class SliceOutput(BaseModel):
    """Step 1 完整输出。"""
    feature_points: list[FeaturePoint]
    coverage_self_check: CoverageSelfCheck
