"""PR4.2：Step 1 Slicer Agent 测试。

策略：monkey-patch `_llm_mod.chat` 不发 HTTP；构造 LLM 输出 JSON 直接验证。
覆盖：
  - happy path：Schema 通过 + 后端覆盖校验通过
  - 漏切 critical KP → 触发一次重试后修正
  - 漏切耗尽重试次数 → SliceResult 带 uncovered_critical
  - LLM 抛异常 → error 字段非空、不崩
  - Schema 校验失败 → error 字段非空
  - MAX_KPS_IN_PROMPT 截断
"""
from __future__ import annotations

import json

import pytest

from backend.agents.case_gen import slicer as slicer_mod
from backend.agents.case_gen.slicer import Slicer
from backend.core.llm import LLMConfig
from backend.schemas.knowledge_point import KnowledgePoint, KPSource


PROJECT = "demo"


def _kp(kp_id: str, ktype: str, module: str = "登录",
        content: str = "示例规则") -> KnowledgePoint:
    return KnowledgePoint(
        kp_id=kp_id, type=ktype, content=content, module=module,
        source=KPSource(file="f.md", chunk_id="f.md::0::h"),
        doc_version="v1", extracted_at="2026-01-01T00:00:00Z",
    )


def _fp_json(fp_id: str, module: str, related: list[str],
             priority: str = "P1") -> dict:
    return {
        "fp_id": fp_id,
        "name": fp_id,
        "description": "desc",
        "module": module,
        "related_kp_ids": related,
        "related_chunk_ids": [],
        "priority": priority,
    }


def _slice_output(fps: list[dict], total_kps: int,
                  covered_kps: int, uncovered: list[str] | None = None) -> str:
    payload = {
        "feature_points": fps,
        "coverage_self_check": {
            "total_kps_input": total_kps,
            "kps_covered_by_feature_points": covered_kps,
            "uncovered_kp_ids": uncovered or [],
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def _cfg() -> LLMConfig:
    return LLMConfig(base_url="https://x/v1", api_key="sk-x", model="m")


# ---- happy path ----------------------------------------------------------

def test_run_happy_path(monkeypatch, tmp_settings):
    kps = [
        _kp("KP_登录_ac_0001", "acceptance_criteria"),
        _kp("KP_登录_br_0001", "business_rule"),
    ]
    out = _slice_output(
        [_fp_json("FP_登录_001", "登录", ["KP_登录_ac_0001", "KP_登录_br_0001"], "P0")],
        total_kps=2, covered_kps=2,
    )
    calls = []
    def fake_chat(messages, cfg, **kw):
        calls.append(messages)
        return out
    monkeypatch.setattr(slicer_mod._llm_mod, "chat", fake_chat)

    agent = Slicer(project=PROJECT)
    result = agent.run("为登录生成用例", kps, chunks=[], llm_cfg=_cfg())

    assert result.error is None
    assert result.slice_output is not None
    assert len(result.slice_output.feature_points) == 1
    assert result.uncovered_critical == []
    assert result.llm_calls == 1
    assert result.retries == 0
    assert len(calls) == 1


def test_retry_on_uncovered_critical(monkeypatch, tmp_settings):
    """第一轮漏切 KP_br_0002 → 重试后 LLM 补齐。"""
    kps = [
        _kp("KP_登录_br_0001", "business_rule"),
        _kp("KP_登录_br_0002", "business_rule"),
    ]
    first = _slice_output(
        [_fp_json("FP_登录_001", "登录", ["KP_登录_br_0001"])],
        total_kps=2, covered_kps=1,
    )
    second = _slice_output(
        [_fp_json("FP_登录_001", "登录",
                  ["KP_登录_br_0001", "KP_登录_br_0002"])],
        total_kps=2, covered_kps=2,
    )
    responses = iter([first, second])
    def fake_chat(messages, cfg, **kw):
        return next(responses)
    monkeypatch.setattr(slicer_mod._llm_mod, "chat", fake_chat)

    agent = Slicer(project=PROJECT)
    result = agent.run("q", kps, chunks=[], llm_cfg=_cfg())

    assert result.error is None
    assert result.uncovered_critical == []
    assert result.retries == 1
    assert result.llm_calls == 2


def test_retry_exhausted_returns_missing(monkeypatch, tmp_settings):
    """两轮都漏切 → SliceResult.uncovered_critical 记录，不抛异常。"""
    kps = [_kp("KP_登录_br_0001", "business_rule")]
    no_cover = _slice_output(
        [_fp_json("FP_登录_001", "登录", [])],
        total_kps=1, covered_kps=0, uncovered=["KP_登录_br_0001"],
    )
    def fake_chat(messages, cfg, **kw):
        return no_cover
    monkeypatch.setattr(slicer_mod._llm_mod, "chat", fake_chat)

    agent = Slicer(project=PROJECT)
    result = agent.run("q", kps, chunks=[], llm_cfg=_cfg(),
                       max_coverage_retries=1)
    assert result.slice_output is not None
    assert result.uncovered_critical == ["KP_登录_br_0001"]
    assert result.retries == 1
    # 调用次数 = 初次 + 1 重试 = 2
    assert result.llm_calls == 2


def test_non_critical_kp_missing_is_ok(monkeypatch, tmp_settings):
    """只缺 input_constraint（非 critical）——不触发重试。"""
    kps = [
        _kp("KP_登录_ac_0001", "acceptance_criteria"),
        _kp("KP_登录_ic_0001", "input_constraint"),
    ]
    out = _slice_output(
        [_fp_json("FP_登录_001", "登录", ["KP_登录_ac_0001"])],
        total_kps=2, covered_kps=1,
    )
    def fake_chat(messages, cfg, **kw):
        return out
    monkeypatch.setattr(slicer_mod._llm_mod, "chat", fake_chat)

    agent = Slicer(project=PROJECT)
    result = agent.run("q", kps, chunks=[], llm_cfg=_cfg())
    assert result.error is None
    assert result.uncovered_critical == []   # 非 critical 的漏切不算数
    assert result.retries == 0


def test_llm_exception_returns_error(monkeypatch, tmp_settings):
    kps = [_kp("KP_登录_br_0001", "business_rule")]
    def boom(messages, cfg, **kw):
        raise RuntimeError("network down")
    monkeypatch.setattr(slicer_mod._llm_mod, "chat", boom)

    agent = Slicer(project=PROJECT)
    result = agent.run("q", kps, chunks=[], llm_cfg=_cfg())
    assert result.error is not None
    assert "network down" in result.error
    assert result.slice_output is None


def test_schema_error_returns_error(monkeypatch, tmp_settings):
    kps = [_kp("KP_登录_br_0001", "business_rule")]
    # 返回非法结构：缺 coverage_self_check 这种必填字段
    bad = json.dumps({"feature_points": []})
    def fake_chat(messages, cfg, **kw):
        return bad
    monkeypatch.setattr(slicer_mod._llm_mod, "chat", fake_chat)

    agent = Slicer(project=PROJECT)
    result = agent.run("q", kps, chunks=[], llm_cfg=_cfg())
    assert result.error is not None
    assert "Schema 校验失败" in result.error
    assert result.slice_output is None


def test_prompt_truncates_excess_kps(monkeypatch, tmp_settings):
    """超过 MAX_KPS_IN_PROMPT 的 kps 应被截掉，user prompt 只含前 30 条。"""
    kps = [_kp(f"KP_a_{i:04d}", "business_rule") for i in range(35)]
    # 只覆盖前 30 条
    fps = [_fp_json("FP_a_001", "登录", [kp.kp_id for kp in kps[:30]])]
    out = _slice_output(fps, total_kps=30, covered_kps=30)

    captured = {}
    def fake_chat(messages, cfg, **kw):
        captured["msgs"] = messages
        return out
    monkeypatch.setattr(slicer_mod._llm_mod, "chat", fake_chat)

    agent = Slicer(project=PROJECT)
    result = agent.run("q", kps, chunks=[], llm_cfg=_cfg())
    assert result.error is None
    user_msg = captured["msgs"][-1]["content"]
    # 第 31 条（KP_a_0030）不应出现在 prompt 里
    assert "KP_a_0029" in user_msg
    assert "KP_a_0030" not in user_msg
    # 后端也只统计前 30 条 → 没有 uncovered
    assert result.uncovered_critical == []


def test_prompt_includes_chunks(monkeypatch, tmp_settings):
    kps = [_kp("KP_登录_br_0001", "business_rule")]
    chunks = [
        {"chunk_id": "f.md::0", "source": "f.md", "text": "用户登录需要手机号"},
        {"chunk_id": "f.md::1", "source": "f.md", "text": "校验密码长度"},
    ]
    out = _slice_output(
        [_fp_json("FP_登录_001", "登录", ["KP_登录_br_0001"])],
        total_kps=1, covered_kps=1,
    )
    captured = {}
    def fake_chat(messages, cfg, **kw):
        captured["msgs"] = messages
        return out
    monkeypatch.setattr(slicer_mod._llm_mod, "chat", fake_chat)

    agent = Slicer(project=PROJECT)
    agent.run("q", kps, chunks=chunks, llm_cfg=_cfg())
    user_msg = captured["msgs"][-1]["content"]
    assert "f.md::0" in user_msg
    assert "f.md::1" in user_msg


def test_retry_prompt_contains_missing_ids(monkeypatch, tmp_settings):
    """重试时的 user message 应包含漏切的 kp_id。"""
    kps = [
        _kp("KP_登录_br_0001", "business_rule"),
        _kp("KP_登录_br_0002", "business_rule"),
    ]
    first = _slice_output(
        [_fp_json("FP_登录_001", "登录", ["KP_登录_br_0001"])],
        total_kps=2, covered_kps=1,
    )
    second = _slice_output(
        [_fp_json("FP_登录_001", "登录",
                  ["KP_登录_br_0001", "KP_登录_br_0002"])],
        total_kps=2, covered_kps=2,
    )
    seen_messages = []
    responses = iter([first, second])
    def fake_chat(messages, cfg, **kw):
        seen_messages.append(list(messages))
        return next(responses)
    monkeypatch.setattr(slicer_mod._llm_mod, "chat", fake_chat)

    agent = Slicer(project=PROJECT)
    result = agent.run("q", kps, chunks=[], llm_cfg=_cfg())
    assert result.error is None
    # 第 2 次调用的最后一条 user 消息必须提到 KP_登录_br_0002
    retry_user = seen_messages[1][-1]
    assert retry_user["role"] == "user"
    assert "KP_登录_br_0002" in retry_user["content"]
