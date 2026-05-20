"""CaseGenPipeline 的 REST 路由。挂载于 /api/case-gen/* 下。

所有路由均 feature-flag 受控（enable_case_gen_pipeline）：关闭时返回 403，
避免新能力在未启用时被误触发。

路由清单：
  POST   /start                                    — 新建流水线（不跑任何步骤）
  GET    /list?project=                            — 当前项目下所有流水线摘要
  GET    /{project}/{pipeline_id}                  — 单条流水线完整 state + 各步产物
  POST   /{project}/{pipeline_id}/step/{n}/run     — 跑第 n 步（按 prereq 校验）
  PUT    /{project}/{pipeline_id}/step/{n}/output  — 接受用户编辑，后续步骤自动置 pending
  POST   /{project}/{pipeline_id}/rollback         — 回退到指定步（body: step_n）
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api.routes_settings import get_runtime_features
from backend.core.llm import LLMConfig
from backend.services import case_gen_service


router = APIRouter()


class _LLMSettings(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class StartBody(BaseModel):
    project: str
    question: str = Field(..., min_length=1, max_length=2000)
    llm: _LLMSettings
    mentions: Optional[list[str]] = None
    filters: Optional[dict] = None


class RunStepBody(BaseModel):
    llm: _LLMSettings


class UserEditBody(BaseModel):
    payload: dict


class RollbackBody(BaseModel):
    step_n: int = Field(..., ge=1, le=4)


def _guard() -> None:
    if not get_runtime_features().enable_case_gen_pipeline:
        raise HTTPException(
            403,
            "Case-gen pipeline 未启用。请在 /api/settings/features 打开 enable_case_gen_pipeline。",
        )


def _cfg(llm: _LLMSettings) -> LLMConfig:
    return LLMConfig(llm.base_url, llm.api_key, llm.model)


# ---- 入口 ------------------------------------------------------------------

@router.post("/start")
def start_pipeline(body: StartBody):
    _guard()
    try:
        s = case_gen_service.start(
            body.project, body.question, _cfg(body.llm),
            mentions=body.mentions, filters=body.filters,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return s.model_dump(mode="json")


@router.get("/list")
def list_pipelines(project: str):
    _guard()
    try:
        return {
            "project": project,
            "pipelines": case_gen_service.list_for_project(project),
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---- 单条 ------------------------------------------------------------------

@router.get("/{project}/{pipeline_id}")
def get_pipeline(project: str, pipeline_id: str):
    _guard()
    try:
        s = case_gen_service.get_state(project, pipeline_id)
    except FileNotFoundError:
        raise HTTPException(404, f"pipeline not found: {pipeline_id}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    step_outputs = {
        str(n): case_gen_service.read_step_output(project, pipeline_id, n)
        for n in (1, 2, 3, 4)
    }
    return {"state": s.model_dump(mode="json"), "step_outputs": step_outputs}


@router.post("/{project}/{pipeline_id}/step/{n}/run")
def run_step(project: str, pipeline_id: str, n: int, body: RunStepBody):
    _guard()
    if n not in (1, 2, 3, 4):
        raise HTTPException(400, "step must be 1..4")
    try:
        state, out = case_gen_service.run_step(
            project, pipeline_id, n, _cfg(body.llm),
        )
    except FileNotFoundError:
        raise HTTPException(404, f"pipeline not found: {pipeline_id}")
    except RuntimeError as e:
        # 状态机拒绝（并发 / prereq 未完成）
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "ok": out.ok,
        "step_n": out.step_n,
        "error": out.error,
        "state": state.model_dump(mode="json"),
        "payload": out.payload,
    }


@router.put("/{project}/{pipeline_id}/step/{n}/output")
def user_edit(project: str, pipeline_id: str, n: int, body: UserEditBody):
    _guard()
    if n not in (1, 2, 3, 4):
        raise HTTPException(400, "step must be 1..4")
    try:
        state = case_gen_service.apply_user_edit(
            project, pipeline_id, n, body.payload,
        )
    except FileNotFoundError:
        raise HTTPException(404, f"pipeline not found: {pipeline_id}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return state.model_dump(mode="json")


@router.post("/{project}/{pipeline_id}/rollback")
def rollback(project: str, pipeline_id: str, body: RollbackBody):
    _guard()
    try:
        state = case_gen_service.rollback(project, pipeline_id, body.step_n)
    except FileNotFoundError:
        raise HTTPException(404, f"pipeline not found: {pipeline_id}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return state.model_dump(mode="json")
