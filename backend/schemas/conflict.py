"""跨文档需求冲突（ConflictPair）数据模型。

设计背景：同一需求在不同文档里的描述如果出现数值、枚举、流程或约束上的分歧，
会让 LLM 生成的测试用例自相矛盾。ConflictDetector 负责把这些"可疑配对"
沉淀成 ConflictPair 记录，交由用户标注"以哪一条为准"。

字段规则与 KnowledgePoint 家族保持一致：ISO8601 UTC 时间字符串、中文模块名。
文件布局见 backend/core/conflict_store.py 顶注。
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# 冲突类型（先覆盖主要形态，后续可无痛扩展）
ConflictType = Literal[
    "numeric",        # 数值不一致：最大次数 5 vs 10、金额上限不同
    "enum",           # 枚举/取值集合不一致
    "rule",           # 业务规则冲突：A 要求强校验、B 允许空
    "flow",           # 流程/顺序冲突
    "acceptance",     # 验收标准相互矛盾
    "other",
]

# 严重度：影响生成用例时的优先级排序
Severity = Literal["high", "medium", "low"]

# 用户对冲突的处置状态
Resolution = Literal[
    "unresolved",     # 初始
    "accept_first",   # 以 kp_ids[0] 为准
    "accept_second",  # 以 kp_ids[1] 为准
    "manual",         # 手工合并 / 另外处理
    "false_positive", # 误报
]


class ConflictPair(BaseModel):
    """持久化到 conflicts.json 的一条冲突记录。

    - `kp_ids` 当前只保留二元对比；未来扩多元时再改。顺序稳定（较早的 kp_id 在前）。
    - `module` 从两条 KP 推出，任一存在即记录；两条分属不同模块时填第一条。
    """
    conflict_id: str                      # cf_<project_short>_<seq:04d>
    kp_ids: list[str] = Field(..., min_length=2, max_length=2)
    type: ConflictType
    severity: Severity = "medium"
    module: Optional[str] = None
    description: str = Field(..., max_length=500)     # LLM 给出的一句话诊断
    evidence: Optional[str] = None                     # 可选：逐字摘录的关键片段
    detected_at: str                                   # ISO8601 UTC
    detector_version: str = "v1"                       # 检测器版本，便于迭代后重跑
    resolution: Resolution = "unresolved"
    resolution_note: str = ""                          # 用户标注/说明
    resolved_at: Optional[str] = None
    # 供 UI 展示：两条 KP 简短内容（检测时快照，避免前端再查）
    kp_contents: list[str] = Field(default_factory=list, max_length=2)


# ---- LLM judge 输出 Schema（不直接落盘） -------------------------------------

class ConflictJudgeItem(BaseModel):
    """LLM 对一对候选 KP 的判断。"""
    is_conflict: bool
    type: ConflictType = "other"
    severity: Severity = "medium"
    description: str = Field("", max_length=500)
    evidence: str = ""


class ConflictJudgeOutput(BaseModel):
    """LLM 批量判断响应。items 与输入候选对一一对应。"""
    items: list[ConflictJudgeItem] = Field(default_factory=list)
