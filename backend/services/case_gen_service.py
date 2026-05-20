"""CaseGenPipeline 的服务层 —— 给 REST 路由的薄封装。

职责：
  - 隔离 HTTP 侧 / 业务侧：路由只认 dict + Pydantic，不直接碰 PipelineState 类
  - 把 pipeline_io 的底层动作编排成"UI 看得懂的动作"
  - 不做 LLM 调用、不做检索（这些都在 CaseGenPipeline 内部）
"""
from __future__ import annotations

from typing import Optional

from backend.agents.case_gen import pipeline_io
from backend.agents.case_gen.pipeline import CaseGenPipeline, StepOutcome
from backend.core.llm import LLMConfig
from backend.schemas.pipeline_state import PipelineState


def start(project: str, question: str, cfg: LLMConfig, *,
          mentions: Optional[list[str]] = None,
          filters: Optional[dict] = None) -> PipelineState:
    pl = CaseGenPipeline(project)
    return pl.start(question, llm_cfg=cfg, mentions=mentions, filters=filters)


def get_state(project: str, pipeline_id: str) -> PipelineState:
    return pipeline_io.load_state(project, pipeline_id)


def list_for_project(project: str) -> list[dict]:
    out: list[dict] = []
    for pid in pipeline_io.list_pipelines(project):
        try:
            s = pipeline_io.load_state(project, pid)
        except Exception:  # 损坏的 state 文件不挡整体列表
            continue
        out.append({
            "pipeline_id": pid,
            "question": s.question,
            "current_step": s.current_step,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
        })
    return out


def run_step(project: str, pipeline_id: str, step_n: int,
             cfg: LLMConfig) -> tuple[PipelineState, StepOutcome]:
    state = pipeline_io.load_state(project, pipeline_id)
    pl = CaseGenPipeline(project)
    out = pl.run_step(state, step_n, llm_cfg=cfg)
    return state, out


def apply_user_edit(project: str, pipeline_id: str, step_n: int,
                    payload: dict) -> PipelineState:
    state = pipeline_io.load_state(project, pipeline_id)
    pl = CaseGenPipeline(project)
    pl.apply_user_edit(state, step_n, payload)
    return state


def rollback(project: str, pipeline_id: str, step_n: int) -> PipelineState:
    state = pipeline_io.load_state(project, pipeline_id)
    pl = CaseGenPipeline(project)
    pl.rollback(state, step_n)
    return state


def read_step_output(project: str, pipeline_id: str, step_n: int) -> Optional[dict]:
    return pipeline_io.read_step_output(project, pipeline_id, step_n)
