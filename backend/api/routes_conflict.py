"""ConflictDetector 的 REST 路由。挂载于 /api/conflict/*。

feature flag：enable_conflict_detection。

路由清单：
  POST   /{project}/detect                    — 运行一次检测（LLM 密集）
  GET    /{project}                           — 列出该项目所有冲突记录
  POST   /{project}/{conflict_id}/resolve     — 标注处置状态
  DELETE /{project}/{conflict_id}             — 删除一条冲突
  DELETE /{project}                           — 清空该项目所有冲突
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api.routes_settings import get_runtime_features
from backend.core.llm import LLMConfig
from backend.services import conflict_service


router = APIRouter()


# ---- 请求体 ----------------------------------------------------------------

class LLMBody(BaseModel):
    base_url: str
    api_key: str
    model: str


class DetectBody(BaseModel):
    llm: LLMBody
    sim_low: float = Field(0.75, ge=0.0, le=1.0)
    sim_high: float = Field(0.99, ge=0.0, le=1.0)
    modules: Optional[list[str]] = None


ResolutionValue = Literal[
    "unresolved", "accept_first", "accept_second", "manual", "false_positive",
]


class ResolveBody(BaseModel):
    resolution: ResolutionValue
    note: str = ""


# ---- 守卫 ------------------------------------------------------------------

def _guard() -> None:
    if not get_runtime_features().enable_conflict_detection:
        raise HTTPException(
            403,
            "冲突检测未启用。请在 /api/settings/features 打开 enable_conflict_detection。",
        )


def _cfg(body: LLMBody) -> LLMConfig:
    return LLMConfig(base_url=body.base_url, api_key=body.api_key, model=body.model)


# ---- 路由 ------------------------------------------------------------------

@router.post("/{project}/detect")
def detect(project: str, body: DetectBody):
    _guard()
    if body.sim_low >= body.sim_high:
        raise HTTPException(400, "sim_low 必须小于 sim_high")
    try:
        return conflict_service.run_detection(
            project, _cfg(body.llm),
            sim_low=body.sim_low, sim_high=body.sim_high,
            modules=body.modules,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{project}")
def list_conflicts(project: str):
    _guard()
    return {"project": project, "conflicts": conflict_service.list_all(project)}


@router.post("/{project}/{conflict_id}/resolve")
def resolve(project: str, conflict_id: str, body: ResolveBody):
    _guard()
    try:
        return conflict_service.resolve(
            project, conflict_id,
            resolution=body.resolution, note=body.note,
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@router.delete("/{project}/{conflict_id}")
def delete_conflict(project: str, conflict_id: str):
    _guard()
    ok = conflict_service.delete(project, conflict_id)
    if not ok:
        raise HTTPException(404, f"conflict not found: {conflict_id}")
    return {"deleted": conflict_id}


@router.delete("/{project}")
def clear_conflicts(project: str):
    _guard()
    conflict_service.clear(project)
    return {"cleared": True}
