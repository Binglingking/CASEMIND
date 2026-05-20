"""用户反馈（FeedbackRecord）数据模型。

设计意图：把用户对 AI 生成结果的 👍 / 👎 / 编辑行为沉淀成结构化记录，
供 CaseGenerator 读取用作 few-shot（正例），也用于后续模型微调的数据源。

绑定目标以 `target_type` 区分：当前仅支持 "case"（生成的测试用例），
未来可扩展 "kp"（知识点正确性）。
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


TargetType = Literal["case", "kp"]

# kind 设计注意：
#  - "up"   正向：作为 few-shot 正例候选
#  - "down" 负向：仅统计展示，暂不作为 prompt 硬约束（避免 LLM 过拟合用户反模式）
#  - "edit" 修改：记录 before/after，最强学习信号；after 的结构由调用方决定
FeedbackKind = Literal["up", "down", "edit"]


class FeedbackRecord(BaseModel):
    """持久化到 feedback.json 的一条反馈记录。"""
    feedback_id: str                       # fb_<project_slug>_<seq:06d>
    target_type: TargetType = "case"
    target_id: str                         # case_id 或 kp_id
    pipeline_id: Optional[str] = None      # case 场景必填，便于溯源
    module: Optional[str] = None           # 冗余字段，方便按模块聚合统计
    kind: FeedbackKind
    note: str = Field("", max_length=1000) # 用户自述"为什么"
    snapshot: dict = Field(default_factory=dict)   # kind=up/down：记录用例快照；edit：{"before": ...}
    edited_payload: Optional[dict] = None          # kind=edit：用户改后的完整载荷
    created_at: str                        # ISO8601 UTC
    user_tag: str = ""                     # 可选身份标识（本地场景一般留空）
