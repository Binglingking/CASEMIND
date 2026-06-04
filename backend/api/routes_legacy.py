"""历史用例 / 历史 XMind / 反哺候选 / 风格画像 路由。

挂载点：/api/legacy/*

子路由：
  - /cases/*      历史用例 Excel 上传/列表/读取/删除
  - /xmind/*      历史 XMind 上传/列表/读取/删除
  - /inferred/*   反哺候选列表与审核
  - /style/*      风格画像读取
  - /analyze      触发五阶段分析（runner）
  - /column-mapping/*  列映射读取/保存
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from backend.core.legacy import legacy_store
from backend.core.llm import LLMConfig
from backend.schemas.column_mapping import ColumnMapping
from backend.services import legacy_service
from backend.agents.legacy_analyzer import runner as analyzer_runner


router = APIRouter()


# ---------- schemas ----------

class LLMSettings(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class ConfirmMappingBody(BaseModel):
    project: str
    fingerprint: str
    mapping: ColumnMapping


class AnalyzeBody(BaseModel):
    project: str
    llm: LLMSettings
    skip_extract: bool = False
    incremental: bool = False  # 新增：是否启用增量分析


class ReviewBody(BaseModel):
    project: str
    inferred_id: str
    decision: str          # 'accept' | 'reject'
    reviewer: Optional[str] = ""


class BatchReviewBody(BaseModel):
    project: str
    inferred_ids: list[str]
    decision: str          # 'accept' | 'reject'
    reviewer: Optional[str] = ""


# ---------- 历史用例 ----------

@router.get("/cases")
def list_case_files(project: str):
    return {"project": project, "files": legacy_service.list_excel_files(project)}


@router.get("/cases/peek-headers")
async def peek_headers_unsupported():
    raise HTTPException(405, "请使用 POST /api/legacy/cases/peek-headers")


@router.post("/cases/peek-headers")
async def peek_excel_headers(
    project: str = Form(...),
    file: UploadFile = File(...),
):
    """读 Excel 表头给前端列映射弹窗用，不入库。"""
    content = await file.read()
    headers, sheets = legacy_service.peek_excel_headers(content, file.filename or "")
    return {"project": project, "headers": headers, "sheet_names": sheets}


@router.post("/cases/upload")
async def upload_case_excel(
    project: str = Form(...),
    file: UploadFile = File(...),
    confirmed_mapping: Optional[str] = Form(None),
):
    """confirmed_mapping 为 ColumnMapping 的 JSON 字符串。"""
    import json

    content = await file.read()
    mapping_obj: ColumnMapping | None = None
    if confirmed_mapping:
        try:
            mapping_obj = ColumnMapping.model_validate(json.loads(confirmed_mapping))
        except Exception as e:
            raise HTTPException(400, f"confirmed_mapping 解析失败: {e}")
    try:
        result = legacy_service.ingest_excel(
            project, file.filename or "cases.xlsx", content,
            confirmed_mapping=mapping_obj,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "ok": True,
        "file_id": result.file_id,
        "already_parsed": result.already_parsed,
        "case_count": result.case_count,
        "sheet_names": result.sheet_names,
        "fingerprint": result.fingerprint,
        "needs_user_confirm": result.needs_user_confirm,
        "column_mapping": result.column_mapping.model_dump(),
        "warnings": result.warnings,
    }


@router.get("/cases/{file_id}")
def get_case_file(project: str, file_id: str):
    cases = legacy_service.list_excel_cases(project, file_id)
    if not cases:
        # 区分文件不存在 vs 空文件
        meta = next((f for f in legacy_store.list_case_files(project)
                     if f.file_id == file_id), None)
        if meta is None:
            raise HTTPException(404, f"文件不存在: {file_id}")
    return {"project": project, "file_id": file_id, "cases": cases}


@router.delete("/cases/{file_id}")
def delete_case_file(project: str, file_id: str):
    return legacy_service.delete_excel_file(project, file_id)


# ---------- 历史 XMind ----------

@router.get("/xmind")
def list_xmind(project: str):
    return {"project": project, "files": legacy_service.list_xmind_files(project)}


@router.post("/xmind/upload")
async def upload_xmind(
    project: str = Form(...),
    file: UploadFile = File(...),
):
    content = await file.read()
    try:
        result = legacy_service.ingest_xmind(
            project, file.filename or "tree.xmind", content,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "ok": True,
        "file_id": result.file_id,
        "already_parsed": result.already_parsed,
        "node_count": result.node_count,
        "leaf_count": result.leaf_count,
        "warnings": result.warnings,
    }


@router.get("/xmind/{file_id}")
def get_xmind(project: str, file_id: str):
    tree = legacy_service.get_xmind_tree(project, file_id)
    if tree is None:
        raise HTTPException(404, f"XMind 不存在: {file_id}")
    return {"project": project, "file_id": file_id, "tree": tree}


@router.delete("/xmind/{file_id}")
def delete_xmind(project: str, file_id: str):
    return legacy_service.delete_xmind_file(project, file_id)


# ---------- 列映射 ----------

@router.get("/column-mapping")
def get_column_mapping(project: str):
    store = legacy_store.load_column_mapping_store(project)
    return store.model_dump()


@router.post("/column-mapping/confirm")
def confirm_column_mapping(body: ConfirmMappingBody):
    store = legacy_store.load_column_mapping_store(body.project)
    body.mapping.confirmed = True
    store.by_fingerprint[body.fingerprint] = body.mapping
    legacy_store.save_column_mapping_store(body.project, store)
    return {"ok": True, "fingerprint": body.fingerprint}


# ---------- 风格画像 ----------

@router.get("/style")
def get_style(project: str):
    profile = legacy_store.load_style_profile(project)
    if profile is None:
        return {"project": project, "profile": None}
    return {"project": project, "profile": profile.model_dump()}


# ---------- 反哺候选 ----------

@router.get("/inferred")
def list_inferred(project: str, status: str | None = None):
    return {
        "project": project,
        "items": legacy_service.list_inferred(project, status=status),
    }


@router.post("/inferred/review")
def review_inferred(body: ReviewBody):
    try:
        item = legacy_service.review_inferred(
            body.project, body.inferred_id, body.decision,
            reviewer=body.reviewer or "",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "item": item}


@router.post("/inferred/batch-review")
def batch_review_inferred(body: BatchReviewBody):
    try:
        items = legacy_service.batch_review_inferred(
            body.project, body.inferred_ids, body.decision,
            reviewer=body.reviewer or "",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "items": items, "count": len(items)}


@router.post("/inferred/promote")
def promote_inferred(project: str):
    """将 ready_to_build 队列内的反哺候选提升为正式知识点。

    幂等操作：已 promoted 的条目不会被重复处理。
    """
    try:
        result = legacy_service.promote_ready_to_build(project)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True, **result}


@router.get("/inferred/stats")
def inferred_stats(project: str):
    return {"project": project, **legacy_service.inferred_stats(project)}


@router.post("/inferred/revoke")
def revoke_auto_accepted(body: ReviewBody):
    """撤销 AI 自动通过的反哺候选，重置为 pending_review 状态。"""
    try:
        item = legacy_service.revoke_auto_accepted(body.project, body.inferred_id)
        if item is None:
            raise HTTPException(404, f"inferred_id 不存在: {body.inferred_id}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "item": item}


@router.post("/inferred/edit")
def edit_inferred_content(
    project: str = Form(...),
    inferred_id: str = Form(...),
    content: str = Form(...),
    editor: str = Form(""),
):
    """用户二次编辑反哺候选的内容。"""
    try:
        item = legacy_service.update_inferred_content(
            project, inferred_id, content, editor=editor,
        )
        if item is None:
            raise HTTPException(404, f"inferred_id 不存在: {inferred_id}")
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "item": item}


# ---------- 五阶段分析触发 ----------

@router.post("/analyze")
def analyze(body: AnalyzeBody):
    cfg = LLMConfig(body.llm.base_url, body.llm.api_key, body.llm.model)
    try:
        result = analyzer_runner.run(
            body.project, cfg=cfg, skip_extract=body.skip_extract,
            incremental=body.incremental,  # 传递增量分析标志
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return {
        "ok": True,
        "project": result.project,
        "case_units_count": result.case_units_count,
        "xmind_leaves_count": result.xmind_leaves_count,
        "xmind_mid_count": result.xmind_mid_count,
        "llm_calls": result.llm_calls,
        "extracted_count": result.extracted_count,
        "aggregated_count": result.aggregated_count,
        "inferred_count": result.inferred_count,
        "errors": result.errors,
    }


# ---------- 分析进度控制 ----------

@router.get("/analyze/progress")
def get_analysis_progress(project: str):
    """获取分析进度"""
    from backend.agents.legacy_analyzer.progress_tracker import controller_manager
    
    controller = controller_manager.get(project)
    if controller is None:
        return {"project": project, "status": "idle", "message": "没有正在进行的分析"}
    
    return controller.get_progress()


@router.post("/analyze/pause")
def pause_analysis(project: str):
    """暂停分析"""
    from backend.agents.legacy_analyzer.progress_tracker import controller_manager
    
    controller = controller_manager.get(project)
    if controller is None:
        raise HTTPException(404, "没有正在进行的分析")
    
    controller.pause()
    return {"ok": True, "message": "分析已暂停"}


@router.post("/analyze/resume")
def resume_analysis(project: str):
    """继续分析"""
    from backend.agents.legacy_analyzer.progress_tracker import controller_manager
    
    controller = controller_manager.get(project)
    if controller is None:
        raise HTTPException(404, "没有正在进行的分析")
    
    controller.resume()
    return {"ok": True, "message": "分析已继续"}


@router.post("/analyze/cancel")
def cancel_analysis(project: str):
    """取消分析"""
    from backend.agents.legacy_analyzer.progress_tracker import controller_manager
    
    controller = controller_manager.get(project)
    if controller is None:
        raise HTTPException(404, "没有正在进行的分析")
    
    controller.cancel()
    return {"ok": True, "message": "分析已取消"}
