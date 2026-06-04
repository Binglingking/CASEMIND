"""PR1.4：parse_with_schema 测试。

覆盖三个路径：
  1. 首次解析成功
  2. 首次失败 + 无重试 → 抛 SchemaValidationError（不静默降级）
  3. 首次失败 + 有重试 → 修正后成功
"""
from __future__ import annotations

from typing import Optional

import pytest
from pydantic import BaseModel, Field

from backend.core import llm as llm_module
from backend.core.llm import LLMConfig, SchemaValidationError, parse_with_schema


class _Item(BaseModel):
    name: str = Field(..., max_length=20)
    count: int


class _Output(BaseModel):
    items: list[_Item]


def test_parse_success_on_first_try():
    raw = '{"items": [{"name": "apple", "count": 3}]}'
    out = parse_with_schema(raw, _Output)
    assert out.items[0].name == "apple"


def test_parse_success_with_markdown_fence():
    raw = '```json\n{"items": [{"name": "a", "count": 1}]}\n```'
    out = parse_with_schema(raw, _Output)
    assert len(out.items) == 1


def test_parse_invalid_json_without_retry_raises():
    raw = "not json at all {{{"
    with pytest.raises(SchemaValidationError) as excinfo:
        parse_with_schema(raw, _Output)
    assert "JSON" in str(excinfo.value) or "valid" in str(excinfo.value).lower()


def test_parse_schema_validation_error_without_retry():
    # JSON 合法但不符合 Schema（count 应为 int）
    raw = '{"items": [{"name": "x", "count": "not-a-number"}]}'
    with pytest.raises(SchemaValidationError):
        parse_with_schema(raw, _Output)


def test_parse_retry_fixes_output(monkeypatch):
    """模拟 LLM 第一次返回坏 JSON，第二次返回合法 JSON。"""
    call_count = {"n": 0}

    def fake_chat(messages, cfg, temperature=0.2, json_mode=False, timeout=180.0):
        call_count["n"] += 1
        return '{"items": [{"name": "retry-success", "count": 99}]}'

    monkeypatch.setattr(llm_module, "chat", fake_chat)

    bad_raw = "not json at all"
    cfg = LLMConfig(base_url="https://x/api/v1", api_key="k", model="m")
    out = parse_with_schema(
        bad_raw, _Output,
        retry_cfg=cfg,
        retry_messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}],
        max_retries=1,
    )
    assert out.items[0].name == "retry-success"
    assert call_count["n"] == 1


def test_parse_retry_exhausted_raises(monkeypatch):
    """LLM 一直返回坏 JSON，重试用完抛错——且错误信息含校验详情。"""
    def always_bad(messages, cfg, **kwargs):
        return "still not json"

    monkeypatch.setattr(llm_module, "chat", always_bad)

    cfg = LLMConfig(base_url="https://x/api/v1", api_key="k", model="m")
    with pytest.raises(SchemaValidationError) as excinfo:
        parse_with_schema(
            "initial bad", _Output,
            retry_cfg=cfg,
            retry_messages=[{"role": "user", "content": "u"}],
            max_retries=2,
        )
    err = excinfo.value
    assert err.raw_output  # 保留最后一次的原始输出以便调试
    assert err.validation_error  # 错误详情有值


def test_parse_retry_messages_contain_error_feedback(monkeypatch):
    """重试时发给 LLM 的 messages 应该包含"校验错误"说明，让它有修正依据。"""
    captured = {}

    def capture_chat(messages, cfg, temperature=0.2, json_mode=False, timeout=180.0):
        captured["messages"] = messages
        captured["temperature"] = temperature
        captured["json_mode"] = json_mode
        return '{"items": []}'

    monkeypatch.setattr(llm_module, "chat", capture_chat)

    cfg = LLMConfig(base_url="https://x/api/v1", api_key="k", model="m")
    parse_with_schema(
        "bad", _Output,
        retry_cfg=cfg,
        retry_messages=[{"role": "system", "content": "sys"}],
        max_retries=1,
    )
    msgs = captured["messages"]
    assert msgs[-1]["role"] == "user"
    assert "校验" in msgs[-1]["content"] or "JSON" in msgs[-1]["content"]
    # 重试应该强制 temperature=0.0 + json_mode=True
    assert captured["temperature"] == 0.0
    assert captured["json_mode"] is True
