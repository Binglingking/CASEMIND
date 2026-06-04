"""飞书集成 HTTP 路由。挂载点 /api/feishu/*。

总开关：backend.config.Features.enable_feishu_integration
项目级开关：memory/<project>/feishu.json -> enabled + subfeatures.*

凭据未就绪期间：
  - /config 读写正常工作
  - /test 返回 scope 探测结果（mock 返回 'mock'，lark stub 返回 'pending_credentials'）
  - /legacy/import、/docs/export 走 MockFeishuClient 可端到端跑通
  - /webhook、/card_callback、/subscriptions 返回 200 但只做签名校验 + 去重，不分发业务
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Request
from pydantic import BaseModel, Field

from backend.api.routes_settings import get_runtime_features
from backend.integrations.feishu import cards
from backend.integrations.feishu.client import (
    FeishuAPIError,
    get_client,
)
from backend.integrations.feishu.config import load_config, save_config
from backend.integrations.feishu.webhook import handle_webhook
from backend.schemas.column_mapping import ColumnMapping
from backend.schemas.feishu import FeishuConfig, FeishuOwner, FeishuSubfeatures
from backend.services import feishu_sync_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ============ 守卫 ============

def require_feishu_enabled(project: str) -> FeishuConfig:
    """总开关（全局 feature flag）+ 项目级 enabled 双重校验。"""
    if not get_runtime_features().enable_feishu_integration:
        raise HTTPException(403, "飞书集成总开关未启用，请联系管理员")
    cfg = load_config(project)
    if not cfg.enabled:
        raise HTTPException(403, f"项目 {project} 未启用飞书集成，请在设置中开启")
    return cfg


def require_subfeature(name: str) -> Callable[[str], FeishuConfig]:
    """生成子功能守卫依赖。用法：Depends(require_subfeature('f1_import'))"""

    def _dep(project: str) -> FeishuConfig:
        cfg = require_feishu_enabled(project)
        if not getattr(cfg.subfeatures, name, False):
            raise HTTPException(403, f"子功能 {name} 未启用")
        return cfg

    return _dep


# ============ Config ============

class FeishuConfigUpdateBody(BaseModel):
    enabled: Optional[bool] = None
    app_id: Optional[str] = None
    app_secret: Optional[str] = None       # 明文，落盘前自动加密
    verify_token: Optional[str] = None
    encrypt_key: Optional[str] = None
    folder_token: Optional[str] = None
    default_chat_id: Optional[str] = None
    webhook_secret: Optional[str] = None
    owners: Optional[list[FeishuOwner]] = None
    subfeatures: Optional[FeishuSubfeatures] = None


def _redact(cfg: FeishuConfig) -> dict[str, Any]:
    """返回前端时不暴露 secret 明文，只标记是否已配置。"""
    data = cfg.model_dump()
    data["app_secret_configured"] = bool(cfg.app_secret_enc)
    data.pop("app_secret_enc", None)
    return data


@router.get("/config")
def read_config(project: str):
    cfg = load_config(project)
    return _redact(cfg)


@router.put("/config")
def update_config(project: str, body: FeishuConfigUpdateBody):
    cfg = load_config(project)
    updates = body.model_dump(exclude_none=True)
    secret = updates.pop("app_secret", None)
    if secret is not None:
        # 明文 secret 走 save_config 内部加密路径
        cfg.app_secret_enc = secret
    for k, v in updates.items():
        setattr(cfg, k, v)
    saved = save_config(project, cfg)
    return _redact(saved)


@router.post("/test")
def test_connection(project: str):
    """探测当前凭据可用 scope。Mock 客户端返回 'mock'，未就绪 LarkClient 返回 'pending_credentials'。"""
    cfg = load_config(project)
    cli = get_client(project)
    try:
        scopes = cli.probe_scopes()
    except Exception as e:
        return {
            "token_ok": False,
            "error": str(e),
            "scopes": {},
            "using_mock": not bool(cfg.app_id),
        }
    return {
        "token_ok": True,
        "scopes": scopes,
        "using_mock": not bool(cfg.app_id),
        "security_warning": cfg.security_warning,
        "audit_pending": cfg.audit_pending,
    }


# ============ F1: 历史用例导入 ============

class ImportLegacyBody(BaseModel):
    project: str
    url: str
    confirmed_mapping: Optional[ColumnMapping] = None


@router.post("/legacy/import")
def import_legacy(body: ImportLegacyBody):
    cfg = require_subfeature("f1_import")(body.project)
    try:
        result = feishu_sync_service.import_legacy_from_feishu(
            project=body.project,
            url=body.url,
            confirmed_mapping=body.confirmed_mapping,
        )
    except FeishuAPIError as e:
        raise HTTPException(400, f"飞书拉取失败：{e}") from e
    except NotImplementedError as e:
        raise HTTPException(501, str(e)) from e
    return {
        "file_id": result.file_id,
        "already_parsed": result.already_parsed,
        "case_count": result.case_count,
        "sheet_names": result.sheet_names,
        "fingerprint": result.fingerprint,
        "needs_user_confirm": result.needs_user_confirm,
        "column_mapping": result.column_mapping.model_dump(),
        "warnings": result.warnings,
    }


# ============ F8: 用例导出 Sheet ============

class ExportCasesBody(BaseModel):
    project: str
    cases: list[dict[str, Any]] = Field(default_factory=list)
    title: Optional[str] = None


@router.post("/docs/export")
def export_cases(body: ExportCasesBody):
    cfg = require_subfeature("f8_export_sheet")(body.project)
    if not body.cases:
        raise HTTPException(400, "cases 不能为空")
    try:
        result = feishu_sync_service.export_cases_to_sheet(
            project=body.project,
            cases=body.cases,
            title=body.title or "",
        )
    except NotImplementedError as e:
        raise HTTPException(501, str(e)) from e
    return result.to_dict()


# ============ F2: Webhook（凭据就绪后接入业务分发） ============

@router.post("/webhook/{project}")
async def webhook(project: str, request: Request):
    """飞书事件订阅入口。签名校验 + challenge + event 去重。

    当前未做业务分发：返回 accepted 后由后续 PR 接入 F2 / F9 路由。
    """
    if not get_runtime_features().enable_feishu_integration:
        return {"detail": "feishu integration disabled"}
    cfg = load_config(project)
    raw = await request.body()
    headers = {k: v for k, v in request.headers.items()}
    status, payload = handle_webhook(
        raw_body=raw,
        headers=headers,
        encrypt_key=cfg.encrypt_key,
    )
    if status >= 400:
        raise HTTPException(status, payload.get("detail", "webhook error"))
    return payload


# ============ F6: 卡片回调（凭据就绪后接入 KP 审核） ============

@router.post("/card_callback/{project}")
async def card_callback(project: str, request: Request):
    if not get_runtime_features().enable_feishu_integration:
        return {"detail": "feishu integration disabled"}
    cfg = load_config(project)
    raw = await request.body()
    headers = {k: v for k, v in request.headers.items()}
    status, payload = handle_webhook(
        raw_body=raw,
        headers=headers,
        encrypt_key=cfg.encrypt_key,
    )
    if status >= 400:
        raise HTTPException(status, payload.get("detail", "callback error"))
    # 凭据就绪后：解析 payload.event.action.value -> 调 kp_store.update_status
    return {"toast": {"type": "info", "content": "已收到（业务分发待接入）"}}


# ============ F2: 订阅管理（stub） ============

class SubscribeBody(BaseModel):
    project: str
    url: str                                       # 飞书文档/多维表格 URL
    scope: str = "bitable_record_changed"


@router.post("/subscriptions")
def create_subscription(body: SubscribeBody):
    cfg = require_subfeature("f2_sync")(body.project)
    # 真实实现：调 drive.subscribe_file
    raise HTTPException(501, "F2 文档变更订阅待飞书 drive:subscribe 权限就绪后接入")


@router.delete("/subscriptions/{sub_id}")
def delete_subscription(project: str, sub_id: str):
    cfg = require_subfeature("f2_sync")(project)
    raise HTTPException(501, "F2 文档变更订阅待飞书 drive:subscribe 权限就绪后接入")
