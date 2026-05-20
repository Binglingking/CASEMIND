"""用户反馈的 REST 路由。挂载于 /api/feedback/*。

feature flag：enable_feedback_loop。

路由清单：
  POST   /{project}                   — 提交一条反馈
  GET    /{project}                   — 列出（可按 kind / target_id 过滤）
  GET    /{project}/summary           — 聚合统计
  GET    /{project}/examples          — few-shot 候选预览（给用户看 CaseGenerator 会用什么）
  DELETE /{project}/{feedback_id}     — 删除一条
  DELETE /{project}                   — 清空
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.routes_settings import get_runtime_features
from backend.services import feedback_service


router = APIRouter()


# ---- 请求体 ----------------------------------------------------------------

KindValue = Literal["up", "down", "edit"]
TargetTypeValue = Literal["case", "kp"]


class SubmitBody(BaseModel):
    target_id: str = Field(..., min_length=1, max_length=128)
    kind: KindValue
    target_type: TargetTypeValue = "case"
    pipeline_id: Optional[str] = None
    module: Optional[str] = None
    note: str = Field("", max_length=1000)
    snapshot: dict = Field(default_factory=dict)
    edited_payload: Optional[dict] = None
    user_tag: str = ""


def _guard() -> None:
    if not get_runtime_features().enable_feedback_loop:
        raise HTTPException(
            403,
            "反馈闭环未启用。请在 /api/settings/features 打开 enable_feedback_loop。",
        )


# ---- 路由 ------------------------------------------------------------------

@router.post("/{project}")
def submit(project: str, body: SubmitBody):
    _guard()
    return feedback_service.submit(
        project,
        target_id=body.target_id,
        kind=body.kind,
        target_type=body.target_type,
        pipeline_id=body.pipeline_id,
        module=body.module,
        note=body.note,
        snapshot=body.snapshot,
        edited_payload=body.edited_payload,
        user_tag=body.user_tag,
    )


@router.get("/{project}")
def list_feedback(
    project: str,
    kind: Optional[KindValue] = Query(None),
    target_id: Optional[str] = Query(None),
):
    _guard()
    return {
        "project": project,
        "feedback": feedback_service.list_all(project, kind=kind, target_id=target_id),
    }


@router.get("/{project}/summary")
def summary(project: str):
    _guard()
    return feedback_service.summary(project)


@router.get("/{project}/examples")
def examples(project: str,
             module: Optional[str] = Query(None),
             limit: int = Query(3, ge=1, le=10)):
    _guard()
    return {
        "project": project,
        "module": module,
        "examples": feedback_service.select_positive_examples(
            project, module=module, limit=limit,
        ),
    }


@router.delete("/{project}/{feedback_id}")
def delete_one(project: str, feedback_id: str):
    _guard()
    ok = feedback_service.delete(project, feedback_id)
    if not ok:
        raise HTTPException(404, f"feedback not found: {feedback_id}")
    return {"deleted": feedback_id}


@router.delete("/{project}")
def clear(project: str):
    _guard()
    feedback_service.clear(project)
    return {"cleared": True}
