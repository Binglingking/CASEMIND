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
ReviewStatus = Literal["pending", "accepted", "rejected", "auto_accepted"]


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
    """待审核/已审核的反哺候选。

    review_status 说明：
      - pending: 待人工审核（置信度中等，AI 不确定）
      - auto_accepted: AI 高置信度自动通过，已直接写入 KP 库（用户可撤销）
      - accepted: 人工审核通过
      - rejected: 人工/自动拒绝
    """
    inferred_id: str                   # IKP_<sha1[:8]>
    type: KPType
    content: str = Field(..., max_length=300)
    module: str
    aliases: list[str] = Field(default_factory=list, max_length=5)
    source: InferredSource
    # --- 聚合相关字段（Stage 4.5 AI 总结后填充） ---
    aggregated_from: list[InferredSource] = Field(default_factory=list)
    """当本 KP 由多条历史数据归纳而来时，记录所有贡献源。
    空列表表示 1:1 对应（未聚合），非空时 source 字段存放主源。"""
    source_summary: str = ""
    """AI 生成的总结依据，说明归纳了哪些用例/XMind 节点，便于审核追溯。"""
    # --- 审核字段 ---
    confidence: float = 0.7            # 反推默认低于直接抽取
    reasoning: str = ""                # LLM 给出的推理依据，便于审核
    auto_accepted: bool = False
    """True 表示 AI 判定高置信度（≥0.9）自动通过；用户可重置为 pending 以撤销。"""
    extracted_at: str                  # ISO8601 UTC
    review_status: ReviewStatus = "pending"
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    promoted_kp_id: Optional[str] = None   # accepted/auto_accepted 后写入 knowledge_points.json 的 KP id


class InferredBatch(BaseModel):
    """单次分析产出的批次（按上传文件维度）。"""
    file_id: str
    items: list[InferredKnowledgePoint] = Field(default_factory=list)
    generated_at: str
