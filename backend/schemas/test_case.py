"""测试用例数据模型 + 流水线各步的输出 Schema。

详见 docs/design/03_case_gen_pipeline.md §8。
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


Category = Literal["正常", "异常", "边界", "安全", "兼容", "性能"]
Priority = Literal["P0", "P1", "P2", "P3"]


class CaseStep(BaseModel):
    step: int
    action: str = Field(..., max_length=200)
    data: str = ""                   # 必须是具体值，禁止抽象描述（由 Prompt 约束）


class SourceRef(BaseModel):
    """用例到源的引用。至少 kp_id 和 chunk_id 其中一个非空。"""
    kp_id: Optional[str] = None
    chunk_id: Optional[str] = None
    file: str                        # 冗余字段，方便 UI 展示
    section: Optional[str] = None

    @model_validator(mode="after")
    def _at_least_one_ref(self) -> "SourceRef":
        if not self.kp_id and not self.chunk_id:
            raise ValueError("SourceRef 必须至少提供 kp_id 或 chunk_id 其中一个")
        return self


class TestCase(BaseModel):
    case_id: str                     # TC_<module>_<seq:04d>
    title: str = Field(..., max_length=30)
    priority: Priority
    category: Category
    feature_point: str               # fp_id
    related_feature_points: list[str] = Field(default_factory=list)  # 集成用例 ≥2
    preconditions: list[str] = Field(default_factory=list)
    steps: list[CaseStep] = Field(..., min_length=1)
    expected_result: str = Field(..., max_length=500)
    source_refs: list[SourceRef] = Field(..., min_length=1)
    generated_by: str = "case_generator_agent"   # case_generator_agent | merger_agent | user
    confidence: float = 0.9
    created_at: str                  # ISO8601 UTC
    # 集成用例补充时默认 True（UI 必须人工确认后才进入 cases.json）
    needs_review: bool = False


# --- Step 2 (generator) ---

class GenerateSelfCheck(BaseModel):
    normal_count: int
    exception_count: int
    boundary_count: int
    security_count: int
    all_source_refs_valid: bool


class GenerateOutput(BaseModel):
    cases: list[TestCase]
    self_check: GenerateSelfCheck


# --- Step 3 (merger) ---

class DedupeEntry(BaseModel):
    kept: str                        # 保留的 case_id
    dropped: list[str] = Field(default_factory=list)
    similarity: float


class MergeOutput(BaseModel):
    merged_cases: list[TestCase]
    dedupe_log: list[DedupeEntry] = Field(default_factory=list)
    integration_added: list[str] = Field(default_factory=list)  # 集成用例的 case_id 列表


# --- Step 4 (validator) ---

class InvalidCase(BaseModel):
    case: dict                        # 原始 dict（可能是校验前的残缺 case）
    errors: list[str]


class ValidateOutput(BaseModel):
    valid_cases: list[TestCase]
    invalid_cases: list[InvalidCase] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
