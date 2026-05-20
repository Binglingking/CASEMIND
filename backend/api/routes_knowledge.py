"""知识点（KnowledgePoint）CRUD + 重建接口。

详见 docs/design/01 §7 与 docs/design/05。

设计要点：
  - 读取永远返回最新磁盘内容（不做进程内缓存，方便 UI 随时反映编辑）；
  - PUT 把 `edited_by_user` 置 True——后续重建时该条不被 LLM 覆盖；
  - POST /rebuild 同步执行（不引入异步任务框架）；若耗时大可在 UI 上加 loading。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core import kp_store
from backend.schemas.knowledge_point import KPSource, KPType


router = APIRouter()


class KPUpdateBody(BaseModel):
    """PUT 请求体——只允许改少数字段，kp_id / source / extracted_at 不可修改。"""
    content: Optional[str] = Field(None, max_length=300)
    type: Optional[KPType] = None
    module: Optional[str] = None
    aliases: Optional[list[str]] = Field(None, max_length=5)


class KPRebuildBody(BaseModel):
    project: str
    keep_edited: bool = True


# ---- 读取 -----------------------------------------------------------------

@router.get("/points")
def list_points(project: str, module: str | None = None,
                type: str | None = None, q: str | None = None):
    """列出 KP，支持按 module / type 过滤和关键词搜索。"""
    kps = kp_store.load_all(project)

    def _match(kp) -> bool:
        if module and kp.module != module:
            return False
        if type and kp.type != type:
            return False
        if q:
            ql = q.lower()
            blob = f"{kp.content} {kp.module} {' '.join(kp.aliases)}".lower()
            if ql not in blob:
                return False
        return True

    filtered = [kp for kp in kps if _match(kp)]
    return {
        "project": project,
        "total": len(kps),
        "matched": len(filtered),
        "items": [kp.model_dump() for kp in filtered],
    }


@router.get("/stats")
def stats(project: str):
    """KP 统计：按 module / type 计数 + 孤儿数。"""
    kps = kp_store.load_all(project)
    by_module: dict[str, int] = {}
    by_type: dict[str, int] = {}
    orphan = 0
    edited = 0
    for kp in kps:
        by_module[kp.module] = by_module.get(kp.module, 0) + 1
        by_type[kp.type] = by_type.get(kp.type, 0) + 1
        if kp.orphan:
            orphan += 1
        if kp.edited_by_user:
            edited += 1
    return {
        "project": project,
        "total": len(kps),
        "by_module": by_module,
        "by_type": by_type,
        "orphan": orphan,
        "edited_by_user": edited,
    }


# ---- 编辑 -----------------------------------------------------------------

@router.put("/points/{kp_id}")
def update_point(kp_id: str, body: KPUpdateBody, project: str):
    kp = kp_store.find_by_id(project, kp_id)
    if not kp:
        raise HTTPException(404, f"未找到知识点 {kp_id}")
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "至少需要提供一个要修改的字段")
    updates["edited_by_user"] = True
    new_kp = kp.model_copy(update=updates)
    kp_store.upsert_one(project, new_kp)
    return new_kp.model_dump()


@router.delete("/points/{kp_id}")
def delete_point(kp_id: str, project: str):
    ok = kp_store.delete_one(project, kp_id)
    if not ok:
        raise HTTPException(404, f"未找到知识点 {kp_id}")
    return {"ok": True, "kp_id": kp_id}


# ---- 全量重建 -------------------------------------------------------------

@router.post("/rebuild")
def rebuild(body: KPRebuildBody):
    """全量重建。

    MVP 实现：读取现有 memory 缓存里的 chunk 不现实（缓存只有 summary）。
    真正重建需要走一遍 MemoryAgent.build(rebuild_all=True) 并打开 features.enable_knowledge_extraction。
    这里暂时只提供一个"清空 + 置 orphan 提示"的轻量版本——具体的重新抽取由前端触发
    `/api/memory/build` 完成。
    """
    # 暂不在这里触发 LLM；由 /api/memory/build 承担
    # 这里只做 "清空 kp 缓存 + 保留 edited_by_user 条目" 的准备动作
    existing = kp_store.load_all(body.project)
    edited = [kp for kp in existing if kp.edited_by_user]
    kp_store.clear_all(body.project)
    if body.keep_edited and edited:
        # 保留的条目全部打 orphan=True，用户走完 build 后会被重新消化
        kp_store.save_all(body.project, [
            kp.model_copy(update={"orphan": True}) for kp in edited
        ])
    return {
        "ok": True,
        "project": body.project,
        "preserved_edited": len(edited) if body.keep_edited else 0,
        "hint": "已清空知识点缓存。请在「记忆」页触发『重建记忆』以重新抽取（需打开 features.enable_knowledge_extraction）。",
    }
