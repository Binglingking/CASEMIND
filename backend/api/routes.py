from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api import (
    routes_case_gen, routes_conflict, routes_coverage,
    routes_feedback, routes_knowledge, routes_legacy, routes_settings,
)
from backend.core.llm import LLMConfig
from backend.core.project import project_manager
from backend.core.vector_store import VectorStore
from backend.services import (
    build_log_service, folder_service, memory_service, memory_version_service,
    output_service, query_service,
)


router = APIRouter()

# Feature flags 挂到 /api/settings/* 下
router.include_router(routes_settings.router, prefix="/settings")
# 知识点挂到 /api/knowledge/* 下
router.include_router(routes_knowledge.router, prefix="/knowledge")
# 用例生成流水线挂到 /api/case-gen/* 下（受 enable_case_gen_pipeline flag 控制）
router.include_router(routes_case_gen.router, prefix="/case-gen")
# 覆盖率报告挂到 /api/coverage/* 下（受 enable_coverage_report flag 控制）
router.include_router(routes_coverage.router, prefix="/coverage")
# 冲突检测挂到 /api/conflict/* 下（受 enable_conflict_detection flag 控制）
router.include_router(routes_conflict.router, prefix="/conflict")
# 用户反馈挂到 /api/feedback/* 下（受 enable_feedback_loop flag 控制）
router.include_router(routes_feedback.router, prefix="/feedback")
# 历史用例 / 历史 XMind / 反哺候选 挂到 /api/legacy/* 下
router.include_router(routes_legacy.router, prefix="/legacy")


# ---------- schemas ----------

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class FolderBody(BaseModel):
    project: str
    path: str


class LLMSettings(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class ScanBody(BaseModel):
    project: str


class BuildBody(BaseModel):
    project: str
    llm: LLMSettings
    force_files: Optional[list[str]] = None
    rebuild_all: bool = False
    incremental: bool = True


class MemorySaveBody(BaseModel):
    project: str
    memory_md: str
    regenerate_prompt: bool = True


class PromptSaveBody(BaseModel):
    project: str
    prompt_text: str


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class QueryBody(BaseModel):
    project: str
    question: str
    mode: str = "qa"
    top_k: Optional[int] = None
    llm: LLMSettings
    history: Optional[list[ChatMessage]] = None
    mentions: Optional[list[dict]] = None  # [{type: "legacy_case"|"legacy_xmind"|"doc"|"output", ...}]


# ---------- projects ----------

@router.get("/projects")
def list_projects():
    return {"projects": project_manager.list_projects()}


@router.post("/projects")
def create_project(body: ProjectCreate):
    try:
        return project_manager.create(body.name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/projects/{name}/stats")
def project_stats(name: str):
    try:
        return {
            "project": name,
            "vector": VectorStore(name).stats(),
            "folders": folder_service.list_folders_with_stats(name),
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


class ProjectDeleteBody(BaseModel):
    name: str


@router.delete("/projects")
def delete_project(body: ProjectDeleteBody):
    try:
        return project_manager.delete(body.name)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------- folders ----------

@router.get("/folders")
def get_folders(project: str):
    try:
        return {"project": project,
                "folders": folder_service.list_folders_with_stats(project)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/folders")
def add_folder(body: FolderBody):
    try:
        return folder_service.add_folder(body.project, body.path)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/folders")
def remove_folder(body: FolderBody):
    try:
        return folder_service.remove_folder(body.project, body.path)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/folders/files")
def list_folder_files(project: str, path: str):
    try:
        return folder_service.list_files_of_folder(project, path)
    except ValueError as e:
        raise HTTPException(400, str(e))


class OpenFileBody(BaseModel):
    project: str
    path: str


@router.post("/folders/open")
def open_local_file(body: OpenFileBody):
    try:
        return folder_service.open_file(body.project, body.path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))


# ---------- scan / build ----------

@router.post("/scan")
def scan(body: ScanBody):
    try:
        return memory_service.scan(body.project)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/memory/build")
def build_memory(body: BuildBody):
    cfg = LLMConfig(body.llm.base_url, body.llm.api_key, body.llm.model)
    try:
        return memory_service.build(
            body.project, cfg,
            force_files=body.force_files, rebuild_all=body.rebuild_all,
            incremental=body.incremental,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))


# ---------- memory build progress control ----------

@router.get("/memory/build/progress")
def get_build_progress(project: str):
    """Get memory build progress."""
    from backend.agents.memory_progress_tracker import controller_manager
    controller = controller_manager.get(project)
    if controller is None:
        return {
            "project": project,
            "status": "idle",
            "current_step": 0,
            "total_steps": 6,
            "step_name": "",
            "processed_files": 0,
            "total_files": 0,
            "llm_calls": 0,
            "extracted_kps": 0,
            "elapsed_seconds": 0.0,
            "message": "",
            "error": None,
            "progress_percent": 0,
        }
    return controller.to_dict()


@router.post("/memory/build/pause")
def pause_build(project: str):
    """Pause memory build."""
    from backend.agents.memory_progress_tracker import controller_manager
    controller = controller_manager.get(project)
    if controller is None:
        raise HTTPException(400, "No active build for this project")
    controller.pause()
    return {"ok": True, "message": "Pause requested"}


@router.post("/memory/build/resume")
def resume_build(project: str):
    """Resume paused memory build."""
    from backend.agents.memory_progress_tracker import controller_manager
    controller = controller_manager.get(project)
    if controller is None:
        raise HTTPException(400, "No active build for this project")
    controller.resume()
    return {"ok": True, "message": "Resumed"}


@router.post("/memory/build/cancel")
def cancel_build(project: str):
    """Cancel memory build (preserves existing memory)."""
    from backend.agents.memory_progress_tracker import controller_manager
    controller = controller_manager.get(project)
    if controller is None:
        raise HTTPException(400, "No active build for this project")
    controller.cancel()
    return {"ok": True, "message": "Cancel requested"}


# ---------- memory read/write ----------

@router.get("/memory")
def get_memory(project: str):
    try:
        return memory_service.read(project)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/memory")
def save_memory(body: MemorySaveBody):
    try:
        return memory_service.save(
            body.project, body.memory_md, body.regenerate_prompt,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/memory/prompt")
def save_prompt(body: PromptSaveBody):
    try:
        return memory_service.save_prompt(body.project, body.prompt_text)
    except ValueError as e:
        raise HTTPException(400, str(e))


class MemoryAugmentBody(BaseModel):
    project: str
    info: str
    note: Optional[str] = ""
    llm: LLMSettings


@router.post("/memory/augment")
def augment_memory(body: MemoryAugmentBody):
    cfg = LLMConfig(body.llm.base_url, body.llm.api_key, body.llm.model)
    try:
        return memory_service.augment(body.project, body.info, cfg, body.note or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))


# ---------- query ----------

@router.post("/query")
def query(body: QueryBody):
    mode = body.mode.lower().strip()
    if mode not in {"qa", "chat", "testcase", "xmind"}:
        raise HTTPException(400, "mode must be qa | chat | testcase | xmind")
    cfg = LLMConfig(body.llm.base_url, body.llm.api_key, body.llm.model)
    history = [m.model_dump() for m in (body.history or [])]
    try:
        return query_service.query(
            body.project, body.question, mode, cfg, body.top_k, history,
            mentions=body.mentions or [],
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))


# ---------- outputs ----------

class OutputRenameBody(BaseModel):
    project: str
    kind: str
    old_name: str
    new_name: str


class OutputDeleteBody(BaseModel):
    project: str
    kind: str
    filename: str


@router.get("/outputs")
def list_outputs(project: str, kind: str | None = None):
    try:
        items = output_service.list_outputs(project, kind)
        return {"project": project, "outputs": items}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/outputs/content")
def get_output_content(project: str, kind: str, filename: str):
    try:
        return output_service.read_output_content(project, kind, filename)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/outputs/rename")
def rename_output(body: OutputRenameBody):
    try:
        return output_service.rename_output(body.project, body.kind, body.old_name, body.new_name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/outputs")
def delete_output(body: OutputDeleteBody):
    try:
        return output_service.delete_output(body.project, body.kind, body.filename)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------- memory versions ----------

@router.get("/memory/versions")
def list_memory_versions(project: str):
    try:
        return {"project": project, "versions": memory_version_service.list_versions(project)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/memory/versions/{version_id}")
def get_memory_version(project: str, version_id: str):
    try:
        data = memory_version_service.get_version(project, version_id)
        if data is None:
            raise HTTPException(404, f"版本不存在: {version_id}")
        return data
    except ValueError as e:
        raise HTTPException(400, str(e))


class VersionRestoreBody(BaseModel):
    project: str


@router.post("/memory/versions/{version_id}/restore")
def restore_memory_version(version_id: str, body: VersionRestoreBody):
    try:
        return memory_version_service.restore_version(body.project, version_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------- build history ----------

@router.get("/memory/builds")
def list_builds(project: str):
    return {"project": project, "builds": build_log_service.list_builds(project)}


@router.get("/memory/builds/{build_id}")
def get_build(project: str, build_id: int):
    data = build_log_service.get_build(project, build_id)
    if data is None:
        raise HTTPException(404, f"构建记录不存在: {build_id}")
    return data


class BuildRestoreBody(BaseModel):
    project: str


@router.post("/memory/builds/{build_id}/restore")
def restore_from_build(build_id: int, body: BuildRestoreBody):
    entry = build_log_service.get_build_entry(body.project, build_id)
    if entry is None:
        raise HTTPException(404, f"构建记录不存在: {build_id}")
    vid = entry.get("version_id")
    if not vid:
        raise HTTPException(400, "该构建记录没有关联的版本，无法恢复")
    try:
        return memory_version_service.restore_version(body.project, vid)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------- excel export ----------

from fastapi.responses import Response as FastAPIResponse


class ExcelExportBody(BaseModel):
    project: str
    kind: str
    filename: str


@router.post("/outputs/export-excel")
def export_excel(body: ExcelExportBody):
    from backend.services import excel_service
    import traceback

    if body.kind != "testcase":
        raise HTTPException(400, "Excel export only supported for testcase")
    try:
        data = excel_service.export_testcase_excel(body.project, body.filename)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, f"文件未找到: {str(e)}")
    except Exception as e:
        error_detail = f"导出Excel时发生错误: {str(e)}"
        print(f"[ERROR] Excel export failed:\n{traceback.format_exc()}")
        raise HTTPException(500, error_detail)

    out_name = Path(body.filename).stem + ".xlsx"
    return FastAPIResponse(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
    )


@router.get("/health")
def health():
    return {"ok": True}


# ---------- diagnostics ----------

class EnvCheckBody(BaseModel):
    api_key: Optional[str] = ""


@router.post("/debug/env-check")
def debug_env_check(body: EnvCheckBody):
    """Diagnose what the backend process actually sees for the configured key.
    Returns presence + length only — never the value itself."""
    import os as _os
    from backend.core.llm import _ENV_EXPLICIT_RE, _ENV_BARE_RE, _resolve_api_key

    raw = (body.api_key or "").strip()
    result: dict = {"raw_length": len(raw), "looks_like_env_ref": False}
    if not raw:
        result["verdict"] = "empty"
        result["hint"] = "未填写 API Key。"
        return result

    m_exp = _ENV_EXPLICIT_RE.match(raw)
    m_bare = _ENV_BARE_RE.match(raw) if not m_exp else None
    if m_exp or m_bare:
        name = (m_exp.group(1) or m_exp.group(2)) if m_exp else m_bare.group(1)
        result["looks_like_env_ref"] = True
        result["env_name"] = name
        val = _os.environ.get(name, "")
        result["present_in_process_env"] = bool(val)
        result["value_length"] = len(val)
        # case-insensitive scan to catch e.g. `anthropic_api_key` vs `ANTHROPIC_API_KEY`
        lower = name.lower()
        ci_hits = [k for k in _os.environ.keys() if k.lower() == lower and k != name]
        result["case_insensitive_hits"] = ci_hits
        if val:
            result["verdict"] = "ok"
            result["hint"] = f"后端进程已读取到 `{name}`（长度 {len(val)}）。"
        elif m_bare:
            # 裸大写 NAME 在 env 里找不到 → 旧行为：当字面 key 用
            result["verdict"] = "literal"
            result["hint"] = (
                f"未检测到名为 `{name}` 的环境变量，系统将把该字符串直接当作字面密钥使用。"
                f"如果这是字面 key 就没问题；如果你本意是引用环境变量，"
                f"请改用显式写法 ${{env:{name}}} 以便在找不到时显式报错。"
            )
        else:
            result["verdict"] = "env_missing"
            hint = (
                f"环境变量 `{name}` 在**后端进程**中不可见。最常见原因：\n"
                "1) Windows 用户变量是在**新进程启动时**读取的——设置变量后需要**关闭并重启后端（uvicorn）**，"
                "   已经运行的进程不会感知变量变化；\n"
                "2) 在错误的作用域设置：用户变量只对当前用户新开进程可见，若后端作为服务/其他账户运行，请设置为系统变量；\n"
                "3) 名称大小写不一致（Windows 不敏感，但 Python os.environ 敏感）。"
            )
            if ci_hits:
                hint += f"\n检测到类似名称（大小写不同）：{', '.join(ci_hits)}——请核对。"
            result["hint"] = hint
    else:
        result["verdict"] = "literal"
        result["hint"] = "该值被当作字面密钥（而非环境变量引用）使用。"

    # final resolution test (without leaking the value)
    try:
        resolved = _resolve_api_key(raw)
        result["resolved_length"] = len(resolved)
        result["resolved_ok"] = bool(resolved)
    except RuntimeError as e:
        result["resolved_ok"] = False
        result["resolve_error"] = str(e)
    return result
