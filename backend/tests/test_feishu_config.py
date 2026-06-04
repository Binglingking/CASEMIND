"""飞书配置存取 + 加密降级测试。"""
from __future__ import annotations

import pytest

from backend.integrations.feishu import config as fcfg
from backend.schemas.feishu import FeishuConfig


def test_load_returns_default_when_missing(tmp_settings):
    cfg = fcfg.load_config("p1")
    assert cfg.enabled is False
    assert cfg.app_id == ""
    assert cfg.subfeatures.f1_import is False


def test_save_then_load_roundtrip(tmp_settings):
    cfg = FeishuConfig(enabled=True, app_id="cli_test_123")
    cfg.subfeatures.f1_import = True
    fcfg.save_config("p1", cfg)
    loaded = fcfg.load_config("p1")
    assert loaded.enabled is True
    assert loaded.app_id == "cli_test_123"
    assert loaded.subfeatures.f1_import is True


def test_secret_plaintext_fallback_without_master_key(tmp_settings, monkeypatch):
    monkeypatch.delenv("CASEMIND_MASTER_KEY", raising=False)
    cfg = FeishuConfig(enabled=True, app_id="cli_x", app_secret_enc="raw_secret")
    saved = fcfg.save_config("p1", cfg)
    assert saved.app_secret_enc.startswith("plain:")
    assert saved.security_warning == "plaintext_fallback_no_master_key"
    assert saved.audit_pending is True
    assert fcfg.decrypt_secret(saved.app_secret_enc) == "raw_secret"


def test_secret_encrypted_with_master_key(tmp_settings, monkeypatch):
    pytest.importorskip("cryptography")
    from cryptography.fernet import Fernet
    monkeypatch.setenv("CASEMIND_MASTER_KEY", Fernet.generate_key().decode("utf-8"))
    cfg = FeishuConfig(enabled=True, app_id="cli_x", app_secret_enc="real_secret")
    saved = fcfg.save_config("p1", cfg)
    assert saved.app_secret_enc.startswith("fernet:")
    assert saved.security_warning == ""
    assert saved.audit_pending is False
    assert fcfg.decrypt_secret(saved.app_secret_enc) == "real_secret"


def test_resaving_encrypted_secret_does_not_double_encrypt(tmp_settings, monkeypatch):
    monkeypatch.delenv("CASEMIND_MASTER_KEY", raising=False)
    cfg = FeishuConfig(app_secret_enc="abc")
    fcfg.save_config("p1", cfg)
    loaded = fcfg.load_config("p1")
    # 重新落盘——值已带 plain: 前缀，不应再次加 prefix
    fcfg.save_config("p1", loaded)
    re_loaded = fcfg.load_config("p1")
    assert re_loaded.app_secret_enc == "plain:abc"
