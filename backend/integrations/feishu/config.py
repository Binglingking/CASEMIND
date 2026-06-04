"""项目级飞书配置存取。

存储路径：memory/<project>/feishu.json
敏感字段（app_secret）落盘前调 encrypt_secret() 处理；
若 CASEMIND_MASTER_KEY 未设置 → 明文存储 + 日志 WARN + audit_pending=True。
key 就绪后 scripts/feishu_secret_migrate.py 一次性迁移到密文。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from backend.config import settings
from backend.schemas.feishu import FeishuConfig

logger = logging.getLogger(__name__)

_MASTER_KEY_ENV = "CASEMIND_MASTER_KEY"
_PLAINTEXT_PREFIX = "plain:"
_CIPHER_PREFIX = "fernet:"
_WARNING_PLAINTEXT = "plaintext_fallback_no_master_key"

_warned_once = False


def _get_fernet():
    """返回 Fernet 实例；未配置 master key 或 cryptography 未安装 → None。"""
    global _warned_once
    key = os.environ.get(_MASTER_KEY_ENV, "").strip()
    if not key:
        if not _warned_once:
            logger.warning(
                "[feishu] %s not set, secrets stored in plaintext (audit_pending)",
                _MASTER_KEY_ENV,
            )
            _warned_once = True
        return None
    try:
        from cryptography.fernet import Fernet  # type: ignore
        return Fernet(key.encode("utf-8"))
    except Exception as e:
        logger.warning("[feishu] cryptography unavailable (%s), fallback to plaintext", e)
        return None


def encrypt_secret(plain: str) -> tuple[str, bool]:
    """加密敏感字段。返回 (stored_value, encrypted_flag)。

    encrypted_flag=False 表示降级到明文，调用方应设置 security_warning。
    """
    if not plain:
        return "", True
    f = _get_fernet()
    if f is None:
        return _PLAINTEXT_PREFIX + plain, False
    token = f.encrypt(plain.encode("utf-8")).decode("utf-8")
    return _CIPHER_PREFIX + token, True


def decrypt_secret(stored: str) -> str:
    if not stored:
        return ""
    if stored.startswith(_PLAINTEXT_PREFIX):
        return stored[len(_PLAINTEXT_PREFIX):]
    if stored.startswith(_CIPHER_PREFIX):
        f = _get_fernet()
        if f is None:
            logger.error("[feishu] ciphertext present but master key missing")
            return ""
        try:
            return f.decrypt(stored[len(_CIPHER_PREFIX):].encode("utf-8")).decode("utf-8")
        except Exception as e:
            logger.error("[feishu] decrypt failed: %s", e)
            return ""
    # 兼容旧数据：无前缀视作明文
    return stored


def _config_path(project: str) -> Path:
    return settings.memory_dir / project / "feishu.json"


def load_config(project: str) -> FeishuConfig:
    """读项目飞书配置；文件缺失/损坏 → 默认空配置（enabled=False）。"""
    path = _config_path(project)
    if not path.exists():
        return FeishuConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return FeishuConfig.model_validate(data)
    except Exception as e:
        logger.warning("[feishu] config load failed for %s: %s", project, e)
        return FeishuConfig()


def save_config(project: str, cfg: FeishuConfig) -> FeishuConfig:
    """落盘前确保 app_secret_enc 已加密（若传入明文则就地加密）。"""
    if cfg.app_secret_enc and not (
        cfg.app_secret_enc.startswith(_PLAINTEXT_PREFIX)
        or cfg.app_secret_enc.startswith(_CIPHER_PREFIX)
    ):
        # 视作前端新传入的明文
        enc, ok = encrypt_secret(cfg.app_secret_enc)
        cfg.app_secret_enc = enc
        if not ok:
            cfg.security_warning = _WARNING_PLAINTEXT
            cfg.audit_pending = True
        else:
            cfg.security_warning = ""
            cfg.audit_pending = False

    path = _config_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cfg.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return cfg


def get_app_secret(project: str) -> str:
    """运行期取明文 secret，仅供 client 内部使用。"""
    cfg = load_config(project)
    return decrypt_secret(cfg.app_secret_enc)
