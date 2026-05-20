"""CoverageAnalyzer 的 REST 路由。挂载于 /api/coverage/* 下。

所有路由受 enable_coverage_report feature flag 控制。

路由清单：
  POST /{project}/{pipeline_id}/compute   — 计算并落盘 coverage_report.{md,json}
  GET  /{project}/summary                 — 项目下所有已算出的覆盖率摘要
  GET  /{project}/{pipeline_id}           — 读磁盘上缓存的 coverage_report.json

注意路由顺序：/summary 必须先于 /{pipeline_id}（FastAPI 按定义顺序匹配）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api.routes_settings import get_runtime_features
from backend.services import coverage_service


router = APIRouter()


class ComputeBody(BaseModel):
    sim_threshold: float = Field(0.75, ge=0.0, le=1.0)
    enable_semantic: bool = True


def _guard() -> None:
    if not get_runtime_features().enable_coverage_report:
        raise HTTPException(
            403,
            "Coverage 报告未启用。请在 /api/settings/features 打开 enable_coverage_report。",
        )


@router.post("/{project}/{pipeline_id}/compute")
def compute(project: str, pipeline_id: str, body: ComputeBody):
    _guard()
    try:
        return coverage_service.compute_and_save(
            project, pipeline_id,
            sim_threshold=body.sim_threshold,
            enable_semantic=body.enable_semantic,
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{project}/summary")
def summary(project: str):
    _guard()
    try:
        return {
            "project": project,
            "items": coverage_service.list_summaries(project),
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{project}/{pipeline_id}")
def get_coverage(project: str, pipeline_id: str):
    _guard()
    try:
        data = coverage_service.read_cached(project, pipeline_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if data is None:
        raise HTTPException(404, "coverage report 未生成，请先 POST /compute")
    return data
