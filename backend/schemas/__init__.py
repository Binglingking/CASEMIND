"""pydantic 模型集中定义。

所有跨 Agent / Service / API 流转的结构化数据都在此定义，确保单一真相源。
"""
from backend.schemas.knowledge_point import (
    KnowledgePoint,
    KPSource,
    KPType,
    KPExtractItem,
    KPExtractOutput,
)
from backend.schemas.feature_point import FeaturePoint, SliceOutput, CoverageSelfCheck
from backend.schemas.test_case import (
    TestCase,
    CaseStep,
    SourceRef,
    Category,
    Priority,
    GenerateOutput,
    GenerateSelfCheck,
    MergeOutput,
    ValidateOutput,
)
from backend.schemas.pipeline_state import PipelineState, StepState, StepStatus
from backend.schemas.coverage import KPCoverage, CoverageReport, CoverageStrength

__all__ = [
    "KnowledgePoint", "KPSource", "KPType", "KPExtractItem", "KPExtractOutput",
    "FeaturePoint", "SliceOutput", "CoverageSelfCheck",
    "TestCase", "CaseStep", "SourceRef", "Category", "Priority",
    "GenerateOutput", "GenerateSelfCheck", "MergeOutput", "ValidateOutput",
    "PipelineState", "StepState", "StepStatus",
    "KPCoverage", "CoverageReport", "CoverageStrength",
]
