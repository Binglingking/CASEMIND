"""PR4.6：CaseGenPipeline 编排器测试。

策略：不发 HTTP，不加载 BGE/FAISS。
  - monkey-patch 各 agent 的 `_llm_mod.chat`
  - monkey-patch `merger._emb_mod.embed` 返回确定向量
  - monkey-patch `pipeline.kp_store.load_all` 返回内存 KP 列表
  - monkey-patch `pipeline.VectorStore` 返回 stub（allowed_chunk_ids 可控）
  - step1 始终注入 retrieved_kps/chunks 跳过检索
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from backend.agents.case_gen import pipeline as pipeline_mod
from backend.agents.case_gen import pipeline_io
from backend.agents.case_gen import slicer as slicer_mod
from backend.agents.case_gen import generator as generator_mod
from backend.agents.case_gen import merger as merger_mod
from backend.agents.case_gen.pipeline import CaseGenPipeline
from backend.core.llm import LLMConfig
from backend.schemas.knowledge_point import KnowledgePoint, KPSource


PROJECT = "demo"


# ========== 共用 factories ==================================================

def _kp(kp_id: str, ktype: str = "business_rule",
        module: str = "登录", content: str = "规则") -> KnowledgePoint:
    return KnowledgePoint(
        kp_id=kp_id, type=ktype, content=content, module=module,
        source=KPSource(file="f.md", chunk_id="f.md::0::h"),
        doc_version="v1", extracted_at="2026-01-01T00:00:00Z",
    )


def _cfg() -> LLMConfig:
    return LLMConfig(base_url="https://x/v1", api_key="k", model="m")


def _slice_raw(fp_id="FP_登录_001", module="登录",
               related=("KP_登录_ac_0001",)) -> str:
    return json.dumps({
        "feature_points": [{
            "fp_id": fp_id,
            "name": fp_id,
            "description": "desc",
            "module": module,
            "related_kp_ids": list(related),
            "related_chunk_ids": [],
            "priority": "P1",
            "user_edited": False,
        }],
        "coverage_self_check": {
            "total_kps_input": len(related),
            "kps_covered_by_feature_points": len(related),
            "uncovered_kp_ids": [],
        },
    }, ensure_ascii=False)


def _case_json(case_id, fp_id, module, kp_ref, category="正常") -> dict:
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
        "source_refs": [{"kp_id": kp_ref, "file": "f.md", "section": None}],
        "generated_by": "case_generator_agent",
        "confidence": 0.9,
        "created_at": "2026-04-29T00:00:00Z",
        "needs_review": False,
    }


def _gen_raw(cases) -> str:
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


class _StubVS:
    """VectorStore 的最小替身——只实现 all_chunks() 返回 id 列表。"""
    def __init__(self, *a, **kw):
        pass

    def all_chunks(self):
        return []


# ========== fixture 帮手 ====================================================

@pytest.fixture
def wire(monkeypatch):
    """打桩 kp_store.load_all + VectorStore + merger 的 embedding，返回可配置 handles。"""
    state = {
        "kps": [_kp("KP_登录_ac_0001", "acceptance_criteria")],
        "slice_raw": _slice_raw(),
        "gen_map": {},               # fp_id -> raw str
        "merger_raw": json.dumps({"integration_cases": [], "rationale": "none"}),
        "merger_raise": None,
        "slice_raise": None,
    }

    # kp_store
    monkeypatch.setattr(pipeline_mod.kp_store, "load_all",
                        lambda project: list(state["kps"]))
    # VectorStore
    monkeypatch.setattr(pipeline_mod, "VectorStore", _StubVS)

    # Slicer / Generator / Merger 共享 backend.core.llm.chat —— 用同一个
    # 分发器按 system prompt 区分路由，避免互相覆盖。
    def dispatch_chat(messages, cfg, **kw):
        sys_text = messages[0]["content"] if messages else ""
        user_text = messages[-1]["content"] if messages else ""
        # Slicer prompt
        if "测试需求分析专家" in sys_text or "SliceOutput" in sys_text:
            if state["slice_raise"]:
                raise state["slice_raise"]
            return state["slice_raw"]
        # Merger prompt
        if "测试架构师" in sys_text or "integration_cases" in sys_text:
            if state["merger_raise"]:
                raise state["merger_raise"]
            return state["merger_raw"]
        # Generator prompt（默认）—— 在所有消息里找 fp_id，retry 时 last msg 是修正指令
        all_text = " ".join(m.get("content", "") for m in messages)
        for fp_id, raw in state["gen_map"].items():
            if fp_id in all_text:
                return raw
        return _gen_raw([_case_json(
            "TC_登录_0001", "FP_登录_001", "登录", "KP_登录_ac_0001",
        )])

    monkeypatch.setattr(slicer_mod._llm_mod, "chat", dispatch_chat)

    # merger embedding：任意文本 → 唯一确定向量（防误判重复）
    def fake_embed(texts):
        import hashlib
        out = []
        for t in texts:
            h = int(hashlib.md5(t.encode("utf-8")).hexdigest(), 16)
            v = np.zeros(8, dtype="float32")
            v[h % 8] = 1.0
            out.append(v)
        arr = np.array(out, dtype="float32")
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms
    monkeypatch.setattr(merger_mod._emb_mod, "embed", fake_embed)

    return state


# ========== 测试用例 ========================================================

def test_start_creates_state(tmp_settings, wire):
    pl = CaseGenPipeline(project=PROJECT)
    s = pl.start("测试登录", llm_cfg=_cfg())
    assert pipeline_io.is_valid_pipeline_id(s.pipeline_id)
    assert s.current_step == "step1_pending"
    # state 文件已落盘
    reloaded = pipeline_io.load_state(s.project, s.pipeline_id)
    assert reloaded.question == "测试登录"


def test_run_step1_happy(tmp_settings, wire):
    pl = CaseGenPipeline(project=PROJECT)
    s = pl.start("登录功能", llm_cfg=_cfg())
    kps = [_kp("KP_登录_ac_0001", "acceptance_criteria")]
    out = pl.run_step(s, 1, llm_cfg=_cfg(),
                     retrieved_kps=kps, retrieved_chunks=[])
    assert out.ok
    assert s.current_step == "step1_done"
    assert s.steps["step1"].status == "done"
    saved = pipeline_io.read_step_output(s.project, s.pipeline_id, 1)
    assert saved["feature_points"][0]["fp_id"] == "FP_登录_001"
    assert saved["retrieved_kp_ids"] == ["KP_登录_ac_0001"]
    assert saved["slicer_meta"]["llm_calls"] == 1


def test_step1_llm_failure_marks_failed(tmp_settings, wire):
    wire["slice_raise"] = RuntimeError("network down")
    pl = CaseGenPipeline(project=PROJECT)
    s = pl.start("登录", llm_cfg=_cfg())
    out = pl.run_step(s, 1, llm_cfg=_cfg(),
                     retrieved_kps=[_kp("KP_登录_ac_0001", "acceptance_criteria")],
                     retrieved_chunks=[])
    assert out.ok is False
    assert s.current_step == "failed_at_step1"
    assert s.steps["step1"].status == "failed"
    assert "network" in (s.steps["step1"].error or "")


def test_run_step2_reads_step1_and_calls_generator(tmp_settings, wire):
    pl = CaseGenPipeline(project=PROJECT)
    s = pl.start("登录", llm_cfg=_cfg())
    pl.run_step(s, 1, llm_cfg=_cfg(),
                retrieved_kps=[_kp("KP_登录_ac_0001", "acceptance_criteria")],
                retrieved_chunks=[])
    out2 = pl.run_step(s, 2, llm_cfg=_cfg())
    assert out2.ok
    assert s.current_step == "step2_done"
    saved = pipeline_io.read_step_output(s.project, s.pipeline_id, 2)
    assert saved["total_cases"] == 1
    assert "FP_登录_001" in saved["by_fp"]


def test_step2_all_fps_fail_is_step_failure(tmp_settings, wire):
    wire["gen_map"] = {"FP_登录_001": "not-json"}  # 会让 Schema 校验失败
    pl = CaseGenPipeline(project=PROJECT)
    s = pl.start("登录", llm_cfg=_cfg())
    pl.run_step(s, 1, llm_cfg=_cfg(),
                retrieved_kps=[_kp("KP_登录_ac_0001", "acceptance_criteria")],
                retrieved_chunks=[])
    out2 = pl.run_step(s, 2, llm_cfg=_cfg())
    assert out2.ok is False
    assert s.current_step == "failed_at_step2"


def test_run_full_pipeline(tmp_settings, wire):
    pl = CaseGenPipeline(project=PROJECT)
    s = pl.start("登录", llm_cfg=_cfg())
    outs = pl.run_all(
        s, llm_cfg=_cfg(),
        retrieved_kps=[_kp("KP_登录_ac_0001", "acceptance_criteria")],
        retrieved_chunks=[],
    )
    assert [o.ok for o in outs] == [True, True, True, True]
    assert s.current_step == "completed"
    # 最终产物落盘
    d = pipeline_io.pipeline_dir(s.project, s.pipeline_id)
    cases_file = d / pipeline_io.FINAL_CASES_FILE
    trace_file = d / pipeline_io.TRACE_FILE
    assert cases_file.exists()
    assert trace_file.exists()
    final = json.loads(cases_file.read_text(encoding="utf-8"))
    assert len(final["cases"]) == 1


def test_run_step_rejected_when_prereq_not_done(tmp_settings, wire):
    pl = CaseGenPipeline(project=PROJECT)
    s = pl.start("登录", llm_cfg=_cfg())
    # 没跑 step1 就跑 step2 → 应拒绝
    with pytest.raises(RuntimeError):
        pl.run_step(s, 2, llm_cfg=_cfg())


def test_rollback_resets_later_steps(tmp_settings, wire):
    pl = CaseGenPipeline(project=PROJECT)
    s = pl.start("登录", llm_cfg=_cfg())
    pl.run_all(
        s, llm_cfg=_cfg(),
        retrieved_kps=[_kp("KP_登录_ac_0001", "acceptance_criteria")],
        retrieved_chunks=[],
    )
    assert s.current_step == "completed"
    pl.rollback(s, 2)
    assert s.current_step == "step2_pending"
    assert s.steps["step2"].status == "pending"
    assert s.steps["step3"].status == "pending"
    assert s.steps["step4"].status == "pending"
    # step1 产物仍在
    assert pipeline_io.read_step_output(s.project, s.pipeline_id, 1) is not None


def test_apply_user_edit_invalidates_later(tmp_settings, wire):
    pl = CaseGenPipeline(project=PROJECT)
    s = pl.start("登录", llm_cfg=_cfg())
    pl.run_step(s, 1, llm_cfg=_cfg(),
                retrieved_kps=[_kp("KP_登录_ac_0001", "acceptance_criteria")],
                retrieved_chunks=[])
    pl.run_step(s, 2, llm_cfg=_cfg())
    # 用户改了 step1 产物 → step2 应变回 pending
    edited = pipeline_io.read_step_output(s.project, s.pipeline_id, 1) or {}
    edited.setdefault("user_note", "edited by hand")
    pl.apply_user_edit(s, 1, edited)
    assert s.steps["step1"].user_edited is True
    assert s.steps["step2"].status == "pending"
    # 且允许重跑 step1（status=user_edited_pending 在白名单）
    pl.run_step(s, 1, llm_cfg=_cfg(),
                retrieved_kps=[_kp("KP_登录_ac_0001", "acceptance_criteria")],
                retrieved_chunks=[])
    assert s.current_step == "step1_done"


def test_rerun_same_step_is_allowed(tmp_settings, wire):
    """step1 跑完后再次运行 step1 应成功（不是错误的并发触发）。"""
    pl = CaseGenPipeline(project=PROJECT)
    s = pl.start("登录", llm_cfg=_cfg())
    pl.run_step(s, 1, llm_cfg=_cfg(),
                retrieved_kps=[_kp("KP_登录_ac_0001", "acceptance_criteria")],
                retrieved_chunks=[])
    out = pl.run_step(s, 1, llm_cfg=_cfg(),
                      retrieved_kps=[_kp("KP_登录_ac_0001", "acceptance_criteria")],
                      retrieved_chunks=[])
    assert out.ok


def test_running_step_cannot_be_triggered_again(tmp_settings, wire):
    """手动把 step1 设为 running → 再次 run_step(1) 应被拒。"""
    pl = CaseGenPipeline(project=PROJECT)
    s = pl.start("登录", llm_cfg=_cfg())
    s.steps["step1"].status = "running"
    with pytest.raises(RuntimeError, match="正在运行中"):
        pl.run_step(s, 1, llm_cfg=_cfg(),
                    retrieved_kps=[], retrieved_chunks=[])


def test_default_retrieve_fallback_does_not_crash(tmp_settings, wire, monkeypatch):
    """HybridRetriever 失败时，_retrieve_for_slicer 应返回空 chunks，而非抛错。"""
    # 让 HybridRetriever 在构造时就炸
    import backend.core.hybrid_retriever as hr
    class Boom:
        def __init__(self, *a, **kw):
            raise RuntimeError("faiss missing")
    monkeypatch.setattr(hr, "HybridRetriever", Boom)

    pl = CaseGenPipeline(project=PROJECT)
    s = pl.start("登录", llm_cfg=_cfg())
    kps, chunks = pl._retrieve_for_slicer(s)
    assert chunks == []
    # kps 来自 wire.kp_store.load_all stub
    assert {k.kp_id for k in kps} == {"KP_登录_ac_0001"}
