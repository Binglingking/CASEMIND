"""PR4.3：Step 2 Generator Agent 测试。

要点：
  - monkey-patch _llm_mod.chat，不发 HTTP
  - 单 FP happy path
  - 多 FP 并行，单个失败不影响其他
  - Schema 错误归为 failures，其他 FP 正常
  - to_payload 结构包含 by_fp / failures / total_cases
  - 截断：超过 MAX_KPS_PER_FP 的 related_kp_ids 只取前 N 条进 prompt
  - broken_refs 被计数（self_check.broken_refs_count）
"""
from __future__ import annotations

import json
import threading

import pytest

from backend.agents.case_gen import generator as gen_mod
from backend.agents.case_gen.generator import Generator
from backend.core.llm import LLMConfig
from backend.schemas.feature_point import FeaturePoint
from backend.schemas.knowledge_point import KnowledgePoint, KPSource


PROJECT = "demo"


def _fp(fp_id: str, module: str = "登录",
        related: list[str] | None = None) -> FeaturePoint:
    return FeaturePoint(
        fp_id=fp_id, name=fp_id, description="desc",
        module=module, related_kp_ids=list(related or []),
    )


def _kp(kp_id: str, ktype: str = "business_rule",
        module: str = "登录", content: str = "rule") -> KnowledgePoint:
    return KnowledgePoint(
        kp_id=kp_id, type=ktype, content=content, module=module,
        source=KPSource(file="f.md", chunk_id="f.md::0::h"),
        doc_version="v1", extracted_at="2026-01-01T00:00:00Z",
    )


def _case_json(case_id: str, fp_id: str, module: str,
               category: str = "正常",
               kp_ref: str = "KP_登录_br_0001") -> dict:
    return {
        "case_id": case_id,
        "title": case_id,
        "priority": "P1",
        "category": category,
        "feature_point": fp_id,
        "related_feature_points": [],
        "preconditions": [],
        "steps": [{"step": 1, "action": "操作", "data": "x"}],
        "expected_result": "成功",
        "source_refs": [
            {"kp_id": kp_ref, "file": "f.md", "section": None},
        ],
        "generated_by": "case_generator_agent",
        "confidence": 0.9,
        "created_at": "2026-04-28T00:00:00Z",
        "needs_review": False,
    }


def _out(cases: list[dict]) -> str:
    return json.dumps({
        "cases": cases,
        "self_check": {
            "normal_count": sum(1 for c in cases if c["category"] == "正常"),
            "exception_count": sum(1 for c in cases if c["category"] == "异常"),
            "boundary_count": sum(1 for c in cases if c["category"] == "边界"),
            "security_count": sum(1 for c in cases if c["category"] == "安全"),
            "all_source_refs_valid": True,
        },
    }, ensure_ascii=False)


def _cfg() -> LLMConfig:
    return LLMConfig(base_url="https://x/v1", api_key="k", model="m")


# ---- 单 FP happy path ----------------------------------------------------

def test_generate_single_fp_happy(monkeypatch, tmp_settings):
    fp = _fp("FP_登录_001", "登录", ["KP_登录_br_0001"])
    kps_index = {"KP_登录_br_0001": _kp("KP_登录_br_0001")}
    raw = _out([_case_json("TC_登录_0001", "FP_登录_001", "登录")])
    monkeypatch.setattr(gen_mod._llm_mod, "chat", lambda **kw: raw)

    agent = Generator(project=PROJECT)
    result = agent.run_all([fp], kps_index, llm_cfg=_cfg(), max_parallel=1)
    assert result.total_cases == 1
    assert result.failures == {}
    r = result.results["FP_登录_001"]
    assert r.llm_calls == 1
    assert r.error is None
    assert r.cases[0].case_id == "TC_登录_0001"


# ---- 多 FP：1 成功 1 失败 --------------------------------------------------

def test_multi_fp_one_failure_does_not_block(monkeypatch, tmp_settings):
    fp_ok = _fp("FP_登录_001", "登录", ["KP_登录_br_0001"])
    fp_bad = _fp("FP_登录_002", "登录", ["KP_登录_br_0001"])
    kps_index = {"KP_登录_br_0001": _kp("KP_登录_br_0001")}

    ok_raw = _out([_case_json("TC_登录_0001", "FP_登录_001", "登录")])

    def fake_chat(messages, cfg, **kw):
        # 从 user message 里反向找 fp_id
        user = messages[-1]["content"]
        if "FP_登录_002" in user:
            raise RuntimeError("simulated network error")
        return ok_raw

    monkeypatch.setattr(gen_mod._llm_mod, "chat", fake_chat)

    agent = Generator(project=PROJECT)
    result = agent.run_all([fp_ok, fp_bad], kps_index, llm_cfg=_cfg(), max_parallel=2)
    assert result.total_cases == 1
    assert "FP_登录_001" in result.results
    assert "FP_登录_002" in result.results
    assert result.results["FP_登录_001"].error is None
    assert result.results["FP_登录_002"].error is not None
    assert "FP_登录_002" in result.failures


# ---- Schema 错误 ----------------------------------------------------------

def test_schema_error_marked_as_failure(monkeypatch, tmp_settings):
    fp = _fp("FP_登录_001", "登录", ["KP_登录_br_0001"])
    kps_index = {"KP_登录_br_0001": _kp("KP_登录_br_0001")}
    # 缺 self_check、cases 为空字符串 → 肯定过不了 Schema
    monkeypatch.setattr(gen_mod._llm_mod, "chat",
                        lambda **kw: json.dumps({"cases": "not-a-list"}))

    agent = Generator(project=PROJECT)
    result = agent.run_all([fp], kps_index, llm_cfg=_cfg(), max_parallel=1)
    assert result.total_cases == 0
    assert "FP_登录_001" in result.failures
    assert "Schema" in result.failures["FP_登录_001"]


# ---- payload 结构 ---------------------------------------------------------

def test_to_payload_structure(monkeypatch, tmp_settings):
    fp = _fp("FP_登录_001", "登录", ["KP_登录_br_0001"])
    kps_index = {"KP_登录_br_0001": _kp("KP_登录_br_0001")}
    raw = _out([_case_json("TC_登录_0001", "FP_登录_001", "登录")])
    monkeypatch.setattr(gen_mod._llm_mod, "chat", lambda **kw: raw)

    agent = Generator(project=PROJECT)
    result = agent.run_all([fp], kps_index, llm_cfg=_cfg(), max_parallel=1)
    payload = result.to_payload()
    assert set(payload.keys()) == {"by_fp", "failures", "total_cases", "total_llm_calls"}
    assert "FP_登录_001" in payload["by_fp"]
    fp_block = payload["by_fp"]["FP_登录_001"]
    assert fp_block["cases"][0]["case_id"] == "TC_登录_0001"
    assert fp_block["self_check"]["normal_count"] == 1
    assert fp_block["error"] is None


# ---- 截断：related_kp_ids 超过 MAX_KPS_PER_FP ------------------------------

def test_related_kps_truncated(monkeypatch, tmp_settings):
    too_many = [f"KP_a_{i:04d}" for i in range(20)]
    fp = _fp("FP_登录_001", "登录", too_many)
    kps_index = {kid: _kp(kid) for kid in too_many}
    raw = _out([_case_json("TC_a_0001", "FP_登录_001", "登录", kp_ref="KP_a_0000")])
    captured = {}
    def fake_chat(messages, cfg, **kw):
        captured["msgs"] = messages
        return raw
    monkeypatch.setattr(gen_mod._llm_mod, "chat", fake_chat)

    agent = Generator(project=PROJECT)
    result = agent.run_all([fp], kps_index, llm_cfg=_cfg(), max_parallel=1)
    assert result.results["FP_登录_001"].error is None
    user_msg = captured["msgs"][-1]["content"]
    # 前 15 条（KP_a_0000 ~ KP_a_0014）应该在
    assert "KP_a_0014" in user_msg
    # 第 16 条（KP_a_0015）应该被截掉
    assert "KP_a_0015" not in user_msg


# ---- broken_refs 计数 -----------------------------------------------------

def test_broken_refs_counted(monkeypatch, tmp_settings):
    """case 的 source_refs 引用了未出现在 related_kps 的 kp_id → broken_refs_count > 0。"""
    fp = _fp("FP_登录_001", "登录", ["KP_登录_br_0001"])
    kps_index = {"KP_登录_br_0001": _kp("KP_登录_br_0001")}
    # 故意引用一个不在 allowed 里的 kp
    raw = _out([
        _case_json("TC_登录_0001", "FP_登录_001", "登录", kp_ref="KP_登录_br_9999"),
    ])
    monkeypatch.setattr(gen_mod._llm_mod, "chat", lambda **kw: raw)

    agent = Generator(project=PROJECT)
    result = agent.run_all([fp], kps_index, llm_cfg=_cfg(), max_parallel=1)
    sc = result.results["FP_登录_001"].self_check
    assert sc["broken_refs_count"] == 1


# ---- feature_point 对齐 ---------------------------------------------------

def test_feature_point_auto_aligned(monkeypatch, tmp_settings):
    """LLM 返回的 case.feature_point 偏差时应被后端强制对齐。"""
    fp = _fp("FP_登录_001", "登录", ["KP_登录_br_0001"])
    kps_index = {"KP_登录_br_0001": _kp("KP_登录_br_0001")}
    wrong = _case_json("TC_登录_0001", "FP_不同_999", "登录")
    raw = _out([wrong])
    monkeypatch.setattr(gen_mod._llm_mod, "chat", lambda **kw: raw)

    agent = Generator(project=PROJECT)
    result = agent.run_all([fp], kps_index, llm_cfg=_cfg(), max_parallel=1)
    c = result.results["FP_登录_001"].cases[0]
    assert c.feature_point == "FP_登录_001"   # 对齐后的


# ---- 空输入 --------------------------------------------------------------

def test_empty_fp_list(tmp_settings):
    agent = Generator(project=PROJECT)
    result = agent.run_all([], {}, llm_cfg=_cfg())
    assert result.total_cases == 0
    assert result.results == {}


# ---- 并发确实触发（通过计数 enter/exit） ---------------------------------

def test_parallel_invocations(monkeypatch, tmp_settings):
    """简易并发性验证：max_parallel=3 且 3 个 FP，chat 内用锁断言并发度。"""
    fps = [_fp(f"FP_登录_{i:03d}", "登录", ["KP_登录_br_0001"]) for i in range(1, 4)]
    kps_index = {"KP_登录_br_0001": _kp("KP_登录_br_0001")}
    raw_ok = _out([_case_json("TC_登录_0001", "FP_登录_001", "登录")])

    in_flight = [0]
    peak = [0]
    lock = threading.Lock()
    barrier = threading.Barrier(3, timeout=5)

    def fake_chat(messages, cfg, **kw):
        with lock:
            in_flight[0] += 1
            peak[0] = max(peak[0], in_flight[0])
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        with lock:
            in_flight[0] -= 1
        return raw_ok

    monkeypatch.setattr(gen_mod._llm_mod, "chat", fake_chat)

    agent = Generator(project=PROJECT)
    agent.run_all(fps, kps_index, llm_cfg=_cfg(), max_parallel=3)
    assert peak[0] >= 2   # 至少两个同时在飞
