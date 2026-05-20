"""历史 XMind 数据模型。

来源：用户上传的 .xmind 原生文件 / .md 兜底。
设计要点：
  - 不强加"步骤+预期"模板：节点就是节点
  - 保留完整路径用于检索 + 中间层维度向量化
  - 不解析 marker（团队约定无圆圈数字含义）
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from backend.schemas.parse_warning import ParseWarning


class LegacyXMindNode(BaseModel):
    """单个节点。"""
    node_id: str                          # 树内唯一：file_id + 路径 hash
    title: str
    depth: int                            # 0 = 根
    path: list[str] = Field(default_factory=list)   # 从根到自身（含自身 title）
    parent_id: Optional[str] = None
    children_ids: list[str] = Field(default_factory=list)
    is_leaf: bool = False
    note: str = ""                        # XMind 节点附注（可选）


class LegacyXMindTree(BaseModel):
    """一棵树（一份文件的根节点 + 节点列表）。"""
    file_id: str                          # 文件级唯一 ID，sha1[:8]
    name: str
    ext: str                              # .xmind / .md
    size: int
    mtime: float
    uploaded_at: str
    root_id: str
    nodes: list[LegacyXMindNode] = Field(default_factory=list)
    parse_warnings: list[ParseWarning] = Field(default_factory=list)
    analyzed: bool = False                # 是否已通过五阶段分析
    analyzed_at: Optional[str] = None     # 最后分析时间（ISO8601）

    def by_id(self) -> dict[str, LegacyXMindNode]:
        return {n.node_id: n for n in self.nodes}

    def leaves(self) -> list[LegacyXMindNode]:
        return [n for n in self.nodes if n.is_leaf]
