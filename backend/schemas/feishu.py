"""飞书集成 - 项目级配置 schema。

凭据与子开关都按项目存储：memory/<project>/feishu.json。
app_secret 在磁盘上用 Fernet 加密（若 CASEMIND_MASTER_KEY 缺失则降级明文 + WARN）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class FeishuOwner(BaseModel):
    name: str
    open_id: str


class FeishuSubfeatures(BaseModel):
    f1_import: bool = False
    f2_sync: bool = False
    f3_done_notify: bool = False
    f4_error_alert: bool = False
    f6_review_card: bool = False
    f8_export_sheet: bool = False
    f9_im_bot: bool = False


class FeishuConfig(BaseModel):
    enabled: bool = False
    app_id: str = ""
    app_secret_enc: str = ""           # 加密后或明文（取决于 master key 是否就绪）
    verify_token: str = ""
    encrypt_key: str = ""
    folder_token: str = ""             # 用例导出落到哪个文件夹
    owners: list[FeishuOwner] = Field(default_factory=list)
    default_chat_id: str = ""
    webhook_secret: str = ""
    subfeatures: FeishuSubfeatures = Field(default_factory=FeishuSubfeatures)
    security_warning: str = ""         # 例如 "plaintext_fallback_no_master_key"
    audit_pending: bool = False        # 等 master key 就绪后做迁移
