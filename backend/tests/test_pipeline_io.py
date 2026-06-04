"""PR4.1：CaseGenPipeline 的 IO 基础设施测试。

覆盖：
  - pipeline_id 生成/校验
  - pipeline_dir 创建与计算
  - state 的 create/load/save（含原子写、updated_at 刷新）
  - 状态转移辅助：running/done/failed/rollback/mark_user_edited
  - step 产物 json 的读写
"""
from __future__ import annotations

import json
import time

import pytest

from backend.agents.case_gen import pipeline_io as pio
from backend.schemas.pipeline_state import (
    ContextBudgetSnapshot,
    LLMConfigSnapshot,
)


PROJECT = "demo"


def _llm_snap() -> LLMConfigSnapshot:
    return LLMConfigSnapshot(base_url="https://x/v1", model="claude-3.5")


def _cb_snap() -> ContextBudgetSnapshot:
    return ContextBudgetSnapshot(
        per_call_max_tokens=30000, history_max_chars=12000,
        retrieval_top_k_chunks=8, retrieval_top_k_kps=15,
        step2_max_parallel=4,
    )


# ---- id / 目录 -----------------------------------------------------------

def test_new_pipeline_id_format():
    pid = pio.new_pipeline_id()
    assert pio.is_valid_pipeline_id(pid)
    # 格式：pl_<8>_<6>_<4hex>
    assert pid.startswith("pl_")
    assert len(pid) == len("pl_20260428_160530_a1b2")


def test_invalid_pipeline_id_rejected():
    assert not pio.is_valid_pipeline_id("not_a_pid")
    assert not pio.is_valid_pipeline_id("pl_2026_ok")
    with pytest.raises(ValueError):
        pio.pipeline_dir(PROJECT, "bad_id")


def test_pipeline_dir_create(tmp_settings):
    pid = pio.new_pipeline_id()
    d = pio.pipeline_dir(PROJECT, pid, create=True)
    assert d.exists() and d.is_dir()
    assert d.name == pid


# ---- state create/load/save ---------------------------------------------

def test_create_state_writes_initial(tmp_settings):
    state = pio.create_state(
        PROJECT, "为登录生成用例",
        llm_cfg=_llm_snap(), mentions=["a.md"], filters={"module": "登录"},
        context_budget=_cb_snap(),
    )
    assert state.current_step == "step1_pending"
    assert state.steps["step1"].status == "pending"
    # 文件写了
    p = pio.pipeline_dir(PROJECT, state.pipeline_id) / pio.PIPELINE_STATE_FILE
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["pipeline_id"] == state.pipeline_id
    assert data["filters"] == {"module": "登录"}


def test_load_state_roundtrip(tmp_settings):
    s1 = pio.create_state(
        PROJECT, "q", llm_cfg=_llm_snap(), context_budget=_cb_snap(),
    )
    s2 = pio.load_state(PROJECT, s1.pipeline_id)
    assert s2.pipeline_id == s1.pipeline_id
    assert s2.question == "q"


def test_load_state_missing_raises(tmp_settings):
    with pytest.raises(FileNotFoundError):
        pio.load_state(PROJECT, pio.new_pipeline_id())


def test_save_state_updates_updated_at(tmp_settings):
    s = pio.create_state(PROJECT, "q", llm_cfg=_llm_snap(), context_budget=_cb_snap())
    first = s.updated_at
    time.sleep(0.01)
    pio.save_state(s)
    assert s.updated_at >= first


def test_list_pipelines_sorted(tmp_settings):
    pids = [
        pio.create_state(PROJECT, f"q{i}", llm_cfg=_llm_snap(),
                         context_budget=_cb_snap()).pipeline_id
        for i in range(3)
    ]
    listed = pio.list_pipelines(PROJECT)
    assert sorted(pids) == listed
    assert len(listed) == 3


def test_list_pipelines_empty(tmp_settings):
    assert pio.list_pipelines(PROJECT) == []


# ---- 状态转移 ------------------------------------------------------------

def test_transition_running_and_done(tmp_settings):
    s = pio.create_state(PROJECT, "q", llm_cfg=_llm_snap(), context_budget=_cb_snap())
    pio.transition_to_running(s, 1)
    assert s.current_step == "step1_running"
    assert s.steps["step1"].status == "running"
    assert s.steps["step1"].started_at is not None
    time.sleep(0.01)
    pio.transition_to_done(s, 1, output_file=pio.STEP1_FILE)
    assert s.current_step == "step1_done"
    assert s.steps["step1"].status == "done"
    assert s.steps["step1"].duration_ms >= 0
    assert s.steps["step1"].output_file == pio.STEP1_FILE


def test_transition_to_done_step4_marks_completed(tmp_settings):
    s = pio.create_state(PROJECT, "q", llm_cfg=_llm_snap(), context_budget=_cb_snap())
    pio.transition_to_running(s, 4)
    pio.transition_to_done(s, 4, output_file=pio.STEP4_FILE)
    assert s.current_step == "completed"


def test_transition_to_failed(tmp_settings):
    s = pio.create_state(PROJECT, "q", llm_cfg=_llm_snap(), context_budget=_cb_snap())
    pio.transition_to_running(s, 2)
    pio.transition_to_failed(s, 2, "network boom")
    assert s.current_step == "failed_at_step2"
    assert s.steps["step2"].status == "failed"
    assert "boom" in (s.steps["step2"].error or "")


def test_rollback_resets_higher_steps(tmp_settings):
    s = pio.create_state(PROJECT, "q", llm_cfg=_llm_snap(), context_budget=_cb_snap())
    for n in (1, 2):
        pio.transition_to_running(s, n)
        pio.transition_to_done(s, n, output_file=f"step{n}.json")
    pio.rollback_to(s, 2)
    assert s.current_step == "step2_pending"
    assert s.steps["step2"].status == "pending"
    # step1 不变
    assert s.steps["step1"].status == "done"
    # step3 / step4 也被归零
    assert s.steps["step3"].status == "pending"
    assert s.steps["step4"].status == "pending"


def test_rollback_rejects_out_of_range(tmp_settings):
    s = pio.create_state(PROJECT, "q", llm_cfg=_llm_snap(), context_budget=_cb_snap())
    with pytest.raises(ValueError):
        pio.rollback_to(s, 5)


def test_mark_user_edited_invalidates_later(tmp_settings):
    s = pio.create_state(PROJECT, "q", llm_cfg=_llm_snap(), context_budget=_cb_snap())
    for n in (1, 2, 3):
        pio.transition_to_running(s, n)
        pio.transition_to_done(s, n, output_file=f"step{n}.json")
    pio.mark_user_edited(s, 1)
    assert s.steps["step1"].user_edited is True
    assert s.steps["step1"].status == "user_edited_pending"
    # 后续步回到 pending，output_file 清空
    assert s.steps["step2"].status == "pending"
    assert s.steps["step2"].output_file is None
    assert s.steps["step3"].status == "pending"
    assert s.current_step == "step1_done"


# ---- step 产物 json ------------------------------------------------------

def test_step_output_path_and_read_write(tmp_settings):
    s = pio.create_state(PROJECT, "q", llm_cfg=_llm_snap(), context_budget=_cb_snap())
    payload = {"feature_points": [{"fp_id": "FP_登录_001"}]}
    pio.write_step_output(PROJECT, s.pipeline_id, 1, payload)
    # 路径命名
    p = pio.step_output_path(PROJECT, s.pipeline_id, 1)
    assert p.name == pio.STEP1_FILE
    # 读回
    got = pio.read_step_output(PROJECT, s.pipeline_id, 1)
    assert got == payload


def test_step_output_invalid_step(tmp_settings):
    with pytest.raises(ValueError):
        pio.step_output_path(PROJECT, pio.new_pipeline_id(), 0)
    with pytest.raises(ValueError):
        pio.step_output_path(PROJECT, pio.new_pipeline_id(), 5)


def test_read_step_output_missing_returns_none(tmp_settings):
    s = pio.create_state(PROJECT, "q", llm_cfg=_llm_snap(), context_budget=_cb_snap())
    assert pio.read_step_output(PROJECT, s.pipeline_id, 3) is None
