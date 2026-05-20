"""反哺候选知识点（Inferred Knowledge Point）。

来自历史用例 / XMind 反推的隐性规则，**未审核**前不写入 knowledge_points.json。
落 memory/<project>/legacy/inferred_kps.json。
审核通过后由 services/knowledge 服务转写为正式 KP，source_type="legacy_inferred"。
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from backend.schemas.knowledge_point import KPType


SourceKind = Literal["case", "xmind"]
ReviewStatus = Literal["pending", "accepted", "rejected"]


class InferredSource(BaseModel):
    """溯源到具体的历史用例行号或 XMind 节点路径。"""
    kind: SourceKind
    file: str                          # 上传时的原始文件名
    file_id: str                       # legacy 文件 ID
    case_id: Optional[str] = None      # kind == "case" 时填
    case_row: Optional[int] = None     # 原 Excel 行号
    node_id: Optional[str] = None      # kind == "xmind" 时填
    node_path: list[str] = Field(default_factory=list)  # 完整节点路径


class InferredKnowledgePoint(BaseModel):
    """待审核的反哺候选。"""
    inferred_id: str                   # IKP_<sha1[:8]>
    type: KPType
    content: str = Field(..., max_length=300)
    module: str
    aliases: list[str] = Field(default_factory=list, max_length=5)
    source: InferredSource
    confidence: float = 0.7            # 反推默认低于直接抽取
    reasoning: str = ""                # LLM 给出的推理依据，便于审核
    extracted_at: str                  # ISO8601 UTC
    review_status: ReviewStatus = "pending"
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    promoted_kp_id: Optional[str] = None   # accepted 后写入 knowledge_points.json 的 KP id


class InferredBatch(BaseModel):
    """单次分析产出的批次（按上传文件维度）。"""
    file_id: str
    items: list[InferredKnowledgePoint] = Field(default_factory=list)
    generated_at: str
