"""知识点（Knowledge Point）数据模型。

KP 是从原始文档 chunk 中抽取的原子级、测试导向的知识单元。
设计规则详见 docs/design/01_knowledge_extraction.md。
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


KPType = Literal[
    "business_rule",        # 业务规则
    "input_constraint",     # 输入约束（长度/格式/必填/枚举）
    "boundary",             # 边界条件
    "exception_flow",       # 异常路径
    "acceptance_criteria",  # 验收标准
    "api_spec",             # 接口契约
    "data_field",           # 数据字段定义
]


class KPSource(BaseModel):
    """KP 的源文档定位。"""
    file: str                      # 源文件名（= VectorStore 里的 source 键）
    chunk_id: str                  # 指向具体 chunk（StoredChunk.id），UI 回跳依据
    section: Optional[str] = None  # 章节号或标题（尽力抽取，抽不到为 None）


class KnowledgePoint(BaseModel):
    """持久化到 knowledge_points.json 的完整 KP 记录。"""
    kp_id: str                     # 见 docs/design/01 §3.2 生成规则
    type: KPType
    content: str = Field(..., max_length=300)
    module: str                    # 所属业务模块（中文）
    aliases: list[str] = Field(default_factory=list)  # 同义词/别名，≤5
    source: KPSource
    doc_version: str               # 文档版本标识（优先 Version 头，否则 mtime ISO8601）
    confidence: float = 0.9        # LLM 自评置信度，[0, 1]
    extracted_at: str              # ISO8601 UTC
    edited_by_user: bool = False   # 用户手动编辑过，全量重建时不被 LLM 覆盖
    orphan: bool = False           # 源文档已被删除，UI 需标红提示用户处置


# --- LLM 抽取输出的结构 ---

class KPExtractItem(BaseModel):
    """LLM 单次抽取输出的单个条目。不含 kp_id / source 等后端补全字段。"""
    type: KPType
    content: str = Field(..., max_length=300)
    module: str
    aliases: list[str] = Field(default_factory=list, max_length=5)
    section: Optional[str] = None
    confidence: float = 0.9


class KPExtractOutput(BaseModel):
    """LLM 抽取响应完整 Schema。"""
    items: list[KPExtractItem] = Field(default_factory=list)
