"""流水线状态机。详见 docs/design/03_case_gen_pipeline.md §4。"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


StepStatus = Literal["pending", "running", "done", "failed", "user_edited_pending"]

# 注：允许 "completed" 作为 pipeline 整体收官状态；失败状态用 "failed_at_stepN"。
CurrentStep = Literal[
    "step1_pending", "step1_running", "step1_done",
    "step2_pending", "step2_running", "step2_done",
    "step3_pending", "step3_running", "step3_done",
    "step4_pending", "step4_running", "step4_done",
    "completed",
    "failed_at_step1", "failed_at_step2", "failed_at_step3", "failed_at_step4",
]


class StepState(BaseModel):
    status: StepStatus = "pending"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    output_file: Optional[str] = None            # 相对 pipeline_dir 的文件名
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    error: Optional[str] = None
    user_edited: bool = False
    # 供 UI 展示：当前步的可能操作
    next_action: Optional[str] = None


class ContextBudgetSnapshot(BaseModel):
    """创建 pipeline 时固化一份预算值，避免中途用户改 Settings 影响既有流水线。"""
    per_call_max_tokens: int
    history_max_chars: int
    retrieval_top_k_chunks: int
    retrieval_top_k_kps: int
    step2_max_parallel: int


class LLMConfigSnapshot(BaseModel):
    """创建 pipeline 时的 LLM 配置快照（不含 api_key，敏感信息不落盘）。"""
    base_url: str
    model: str


class PipelineState(BaseModel):
    pipeline_id: str                  # pl_<yyyymmdd>_<hhmmss>_<short_rand>
    project: str
    question: str
    mentions: list[str] = Field(default_factory=list)
    filters: dict = Field(default_factory=dict)
    created_at: str
    updated_at: str
    current_step: CurrentStep = "step1_pending"
    steps: dict[str, StepState] = Field(default_factory=lambda: {
        "step1": StepState(), "step2": StepState(),
        "step3": StepState(), "step4": StepState(),
    })
    llm_cfg_snapshot: LLMConfigSnapshot
    context_budget: ContextBudgetSnapshot
