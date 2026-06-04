from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend.api import (
    routes_batch, routes_case_gen, routes_conflict, routes_coverage,
    routes_feedback, routes_feishu, routes_knowledge, routes_legacy, routes_settings,
)
from backend.config import settings
from backend.core.llm import LLMConfig
from backend.core.project import project_manager
from backend.core.timeutil import utc_iso_z
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
# 飞书集成挂到 /api/feishu/* 下（受 enable_feishu_integration + 项目级 enabled 双重控制）
router.include_router(routes_feishu.router, prefix="/feishu")
# 批量生成（拆分+逐单元生成）挂到 /api/batch/* 下
router.include_router(routes_batch.router, prefix="/batch")


# ---------- schemas ----------

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    owner: Optional[str] = None
    password: Optional[str] = None


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
    images: Optional[list[str]] = None  # 图片 URL 列表


class QueryBody(BaseModel):
    project: str
    question: str
    mode: str = "qa"
    top_k: Optional[int] = None
    llm: LLMSettings
    history: Optional[list[ChatMessage]] = None
    mentions: Optional[list[dict]] = None  # [{type: "legacy_case"|"legacy_xmind"|"doc"|"output", ...}]
    images: Optional[list[str]] = None  # 上传的图片 URL 列表


# ---------- projects ----------

@router.get("/projects")
def list_projects():
    return {"projects": project_manager.list_projects()}


@router.post("/projects")
def create_project(body: ProjectCreate):
    try:
        meta = project_manager.create(body.name)
        if body.owner and body.password:
            meta = project_manager.set_password(body.name, body.owner, body.password)
        return meta
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


class UnlockBody(BaseModel):
    password: str


class SetPasswordBody(BaseModel):
    owner: str
    password: str


class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str


@router.delete("/projects")
def delete_project(body: ProjectDeleteBody):
    try:
        return project_manager.delete(body.name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/projects/{name}/unlock")
def unlock_project(name: str, body: UnlockBody):
    """验证项目密码，成功则返回 ok。"""
    if not project_manager.verify_password(name, body.password):
        raise HTTPException(403, "密码错误")
    meta = project_manager.get_meta(name)
    return {"ok": True, "project": name, "owner": meta.get("owner", "")}


@router.post("/projects/{name}/set-password")
def set_project_password(name: str, body: SetPasswordBody):
    """为项目首次设置密码（或修改密码）。"""
    try:
        meta = project_manager.set_password(name, body.owner, body.password)
        return {"ok": True, **meta}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/projects/{name}/change-password")
def change_project_password(name: str, body: ChangePasswordBody):
    """修改项目密码（需验证原密码）。"""
    try:
        meta = project_manager.change_password(name, body.old_password, body.new_password)
        return {"ok": True, **meta}
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


@router.post("/folders/upload")
async def upload_files(project: str = Form(...), files: list[UploadFile] = File(...)):
    """Upload requirement doc files (.md/.docx/.pdf/.txt/.markdown).
    Files are saved to memory/<project>/uploads/ and auto-registered as a folder."""
    pairs = []
    for f in files:
        content = await f.read()
        pairs.append((f.filename or "unnamed", content))
    try:
        return folder_service.upload_files(project, pairs)
    except ValueError as e:
        raise HTTPException(400, str(e))


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
    if mode not in {"qa", "chat", "testcase", "xmind", "req_analysis"}:
        raise HTTPException(400, "mode must be qa | chat | testcase | xmind | req_analysis")
    cfg = LLMConfig(body.llm.base_url, body.llm.api_key, body.llm.model)
    history = [m.model_dump() for m in (body.history or [])]
    try:
        return query_service.query(
            body.project, body.question, mode, cfg, body.top_k, history,
            mentions=body.mentions or [],
            images=body.images or [],
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))


# ---------- query stream ----------

@router.post("/query/stream")
async def query_stream(body: QueryBody):
    """SSE 流式查询端点。"""
    mode = body.mode.lower().strip()
    if mode not in {"qa", "chat", "testcase", "xmind", "req_analysis"}:
        raise HTTPException(400, "mode must be qa | chat | testcase | xmind | req_analysis")
    cfg = LLMConfig(body.llm.base_url, body.llm.api_key, body.llm.model)
    history = [m.model_dump() for m in (body.history or [])]

    from backend.services.query_service import query_stream as qs

    def _sse_encode(event: str, data: str) -> str:
        """将事件编码为 SSE 格式，支持 data 中包含换行。"""
        lines = [f"event: {event}"]
        for dline in data.split("\n"):
            lines.append(f"data: {dline}")
        return "\n".join(lines) + "\n\n"

    async def event_generator():
        try:
            for evt, text in qs(
                body.project, body.question, mode, cfg, body.top_k, history,
                mentions=body.mentions or [],
                images=body.images or [],
            ):
                yield _sse_encode(evt, text)
        except Exception as e:
            yield _sse_encode("error", str(e))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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


@router.get("/outputs/download")
def download_output(project: str, kind: str, filename: str):
    try:
        target = output_service.output_path(project, kind, filename)
    except ValueError as e:
        raise HTTPException(404, str(e))
    content_type, _ = mimetypes.guess_type(str(target))
    return FileResponse(
        target,
        media_type=content_type or "application/octet-stream",
        filename=target.name,
    )


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


# ---------- image upload ----------

def _image_dir(project: str) -> Path:
    d = project_manager.mem_dir(project) / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


@router.post("/upload")
async def upload_images(project: str = Form(...), images: list[UploadFile] = File(...)):
    """Upload images for chat. Supports PNG, JPG, JPEG, GIF, WebP up to 10 MB each."""
    max_bytes = settings.max_image_size_mb * 1024 * 1024
    result = []
    for img in images:
        # 文件名校验
        fname = (img.filename or "image").strip()
        ext = Path(fname).suffix.lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            raise HTTPException(
                400,
                f"不支持的图片格式: {ext}。允许的格式: {', '.join(sorted(ALLOWED_IMAGE_EXTENSIONS))}",
            )
        content = await img.read()
        if len(content) > max_bytes:
            raise HTTPException(
                400,
                f"图片 {fname} 大小 {len(content) / 1024 / 1024:.1f} MB 超过限制 ({settings.max_image_size_mb} MB)",
            )
        # 校验实际 MIME 类型
        content_type = img.content_type or ""
        if content_type and content_type not in settings.allowed_image_types:
            raise HTTPException(
                400,
                f"不支持的图片类型: {content_type}。允许: {', '.join(settings.allowed_image_types)}",
            )
        # 生成唯一文件名
        ts = int(time.time() * 1000)
        uid = uuid.uuid4().hex[:8]
        safe_name = f"{ts}_{uid}{ext}"
        dest = _image_dir(project) / safe_name
        dest.write_bytes(content)
        url = f"/api/images/{project}/{safe_name}"
        result.append({"filename": safe_name, "original_name": fname, "url": url, "size": len(content)})
    return {"ok": True, "images": result}


@router.get("/images/{project}/{filename}")
def serve_image(project: str, filename: str):
    """Serve uploaded images."""
    p = _image_dir(project) / filename
    if not p.exists():
        raise HTTPException(404, "图片不存在")
    content_type, _ = mimetypes.guess_type(str(p))
    return FileResponse(p, media_type=content_type or "image/png")


# ---------- chats persistence ----------

class ChatsSaveBody(BaseModel):
    project: str
    chats: list[dict]  # 完整的对话列表
    active_id: str = ""  # 当前激活的对话 ID


def _chats_path(project: str) -> Path:
    d = project_manager.mem_dir(project) / "chats"
    d.mkdir(parents=True, exist_ok=True)
    return d / "chats.json"


@router.get("/chats/{project}")
def get_chats(project: str):
    """加载项目的所有对话记录。"""
    try:
        p = _chats_path(project)
        if not p.exists():
            return {"project": project, "chats": [], "active_id": ""}
        data = json.loads(p.read_text(encoding="utf-8"))
        return {
            "project": project,
            "chats": data.get("chats", []),
            "active_id": data.get("active_id", ""),
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/chats/{project}")
def save_chats(project: str, body: ChatsSaveBody):
    """保存项目的所有对话记录。"""
    try:
        p = _chats_path(project)
        data = {
            "chats": body.chats,
            "active_id": body.active_id,
            "saved_at": utc_iso_z(),
        }
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "project": project, "count": len(body.chats)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/health")
def health():
    return {"ok": True}


# ---------- requirement analysis report PDF ----------

class ReqAnalysisReportBody(BaseModel):
    project: str
    analysis_json: str  # JSON string of the analysis result


@router.post("/query/req-analysis/report")
def generate_req_analysis_report(body: ReqAnalysisReportBody):
    """Generate a PDF report for requirement analysis results."""
    try:
        import json as _json
        data = _json.loads(body.analysis_json)
    except Exception:
        raise HTTPException(400, "Invalid analysis JSON")

    try:
        from backend.services.req_analysis_service import generate_pdf_report
        pdf_bytes = generate_pdf_report(body.project, data)
        import base64
        return {
            "ok": True,
            "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
            "filename": f"需求分析报告_{body.project}.pdf",
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"PDF生成失败: {str(e)}")


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
