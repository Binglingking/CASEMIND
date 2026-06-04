"""飞书客户端适配层测试。"""
from __future__ import annotations

import pytest

from backend.integrations.feishu.client import (
    FeishuAPIError,
    LarkFeishuClient,
    MockFeishuClient,
    get_client,
)
from backend.integrations.feishu.config import save_config
from backend.schemas.feishu import FeishuConfig


def test_mock_pull_bitable_returns_fixture():
    cli = MockFeishuClient(project="p1")
    r = cli.pull_bitable("https://feishu.cn/base/abc")
    assert r.headers and r.records
    assert len(r.records) >= 2


def test_mock_rejects_non_feishu_url():
    cli = MockFeishuClient(project="p1")
    with pytest.raises(FeishuAPIError):
        cli.pull_bitable("https://example.com/foo")


def test_mock_send_card_records_calls():
    cli = MockFeishuClient(project="p1")
    cli.send_card("ou_xx", {"k": 1})
    cli.send_card("oc_yy", {"k": 2})
    assert len(cli.sent_cards) == 2
    assert cli.sent_cards[0] == ("ou_xx", {"k": 1})


def test_mock_create_sheet_assigns_unique_tokens():
    cli = MockFeishuClient(project="p1")
    a = cli.create_sheet_with_records("t1", ["h"], [["v1"]])
    b = cli.create_sheet_with_records("t2", ["h"], [["v2"]])
    assert a.sheet_token != b.sheet_token
    assert a.row_count == 1


def test_factory_returns_mock_when_app_id_empty(tmp_settings):
    cli = get_client("p_new")
    assert isinstance(cli, MockFeishuClient)


def test_factory_returns_lark_when_app_id_set(tmp_settings):
    save_config("p_x", FeishuConfig(app_id="cli_real", app_secret_enc="s"))
    cli = get_client("p_x")
    assert isinstance(cli, LarkFeishuClient)
    # Lark stub 调用即抛 NotImplementedError
    with pytest.raises(NotImplementedError):
        cli.pull_bitable("https://feishu.cn/base/abc")
