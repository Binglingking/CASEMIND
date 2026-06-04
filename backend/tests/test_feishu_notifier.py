"""F3 通知钩子测试。

覆盖：守卫各层、目标聚合（chat + owners）、异常吞咽、ingest_excel 集成路径。
"""
from __future__ import annotations

import json

import pytest

from backend.integrations.feishu import config as fcfg
from backend.integrations.feishu import notifier
from backend.integrations.feishu.client import FeishuAPIError, MockFeishuClient
from backend.schemas.feishu import FeishuConfig, FeishuOwner, FeishuSubfeatures


def _enable_global(tmp_settings):
    from backend import config as cfg_mod
    cfg_mod.FEATURES_STORE_PATH.write_text(
        json.dumps({"enable_feishu_integration": True}), encoding="utf-8"
    )


def _project_cfg_full(**overrides):
    base = FeishuConfig(
        enabled=True,
        default_chat_id="oc_chat_x",
        owners=[FeishuOwner(name="Alice", open_id="ou_alice")],
        subfeatures=FeishuSubfeatures(f3_done_notify=True),
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_skipped_when_global_flag_off(tmp_settings):
    # 全局 flag 默认 False
    fcfg.save_config("p1", _project_cfg_full())
    cli = MockFeishuClient(project="p1")
    sent = notifier.notify_legacy_ingest_done(
        project="p1", filename="x.xlsx",
        case_count=1, warnings_count=0, client=cli,
    )
    assert sent == 0
    assert cli.sent_cards == []


def test_skipped_when_project_disabled(tmp_settings):
    _enable_global(tmp_settings)
    fcfg.save_config("p1", _project_cfg_full(enabled=False))
    cli = MockFeishuClient(project="p1")
    sent = notifier.notify_legacy_ingest_done(
        project="p1", filename="x", case_count=1, warnings_count=0, client=cli,
    )
    assert sent == 0
    assert cli.sent_cards == []


def test_skipped_when_subfeature_off(tmp_settings):
    _enable_global(tmp_settings)
    cfg = _project_cfg_full()
    cfg.subfeatures.f3_done_notify = False
    fcfg.save_config("p1", cfg)
    cli = MockFeishuClient(project="p1")
    sent = notifier.notify_legacy_ingest_done(
        project="p1", filename="x", case_count=1, warnings_count=0, client=cli,
    )
    assert sent == 0


def test_sends_to_chat_and_each_owner(tmp_settings):
    _enable_global(tmp_settings)
    cfg = _project_cfg_full(
        owners=[FeishuOwner(name="A", open_id="ou_a"),
                FeishuOwner(name="B", open_id="ou_b")],
    )
    fcfg.save_config("p1", cfg)
    cli = MockFeishuClient(project="p1")
    sent = notifier.notify_legacy_ingest_done(
        project="p1", filename="legacy.xlsx",
        case_count=10, warnings_count=2, client=cli,
    )
    assert sent == 3  # chat + 2 owners
    targets = [t for t, _ in cli.sent_cards]
    assert targets == ["oc_chat_x", "ou_a", "ou_b"]


def test_skipped_when_no_targets(tmp_settings):
    _enable_global(tmp_settings)
    cfg = _project_cfg_full(default_chat_id="", owners=[])
    fcfg.save_config("p1", cfg)
    cli = MockFeishuClient(project="p1")
    sent = notifier.notify_legacy_ingest_done(
        project="p1", filename="x", case_count=1, warnings_count=0, client=cli,
    )
    assert sent == 0


def test_client_failure_is_swallowed(tmp_settings):
    _enable_global(tmp_settings)
    fcfg.save_config("p1", _project_cfg_full())

    class BrokenClient(MockFeishuClient):
        def send_card(self, target, card):  # type: ignore[override]
            raise FeishuAPIError("boom")

    cli = BrokenClient(project="p1")
    # 不抛
    sent = notifier.notify_legacy_ingest_done(
        project="p1", filename="x", case_count=1, warnings_count=0, client=cli,
    )
    assert sent == 0


def test_case_gen_done_notification(tmp_settings):
    _enable_global(tmp_settings)
    fcfg.save_config("p1", _project_cfg_full())
    cli = MockFeishuClient(project="p1")
    sent = notifier.notify_case_gen_done(
        project="p1", pipeline_id="pl_abc",
        case_count=12, warnings_count=0, client=cli,
    )
    assert sent == 2  # chat + 1 owner
    # 卡片正文包含 pipeline_id
    first_card_md = cli.sent_cards[0][1]["elements"][0]["text"]["content"]
    assert "pl_abc" in first_card_md
    assert "12" in first_card_md


def test_legacy_ingest_triggers_notify_when_enabled(tmp_settings, monkeypatch):
    """端到端：ingest_excel 完成后自动调通知。"""
    _enable_global(tmp_settings)
    fcfg.save_config("p_int", _project_cfg_full())

    captured = []

    def fake_notify(*, project, filename, case_count, warnings_count, **_):
        captured.append((project, filename, case_count, warnings_count))
        return 1

    monkeypatch.setattr(
        "backend.integrations.feishu.notifier.notify_legacy_ingest_done",
        fake_notify,
    )

    # 构造一份最小可解析 xlsx
    from openpyxl import Workbook
    import io
    wb = Workbook()
    ws = wb.active
    ws.append(["用例ID", "模块", "标题", "前置条件", "步骤", "预期结果", "优先级"])
    ws.append(["T1", "登录", "正常登录", "已注册", "1. 输入\n2. 提交", "进入首页", "P0"])
    buf = io.BytesIO()
    wb.save(buf)

    from backend.services import legacy_service
    result = legacy_service.ingest_excel(
        project="p_int", filename="t.xlsx", content=buf.getvalue(),
    )
    # 当列映射命中率充分时 case_count>0，且通知被调
    if not result.needs_user_confirm:
        assert len(captured) == 1
        assert captured[0][0] == "p_int"
        assert captured[0][2] >= 1
