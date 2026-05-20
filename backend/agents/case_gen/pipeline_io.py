"""pipeline 目录布局 + state 持久化。

每个 pipeline 对应 outputs/testcases/<project>/<pipeline_id>/ 目录；
state 文件是 `pipeline_state.json`，所有步骤的产物都落盘在同目录。

设计参考 docs/design/03 §3~4：
  - id 格式：pl_<yyyymmdd>_<hhmmss>_<4位随机>（保证排序天然按时间）
  - 状态持久化必须原子（tmp + rename），避免写一半被读到
  - 提供 load_state / save_state / pipeline_dir / list_pipelines 等纯粹的 IO 工具
  - **不含任何业务逻辑**；业务在 CaseGenPipeline 里
"""
from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.config import settings
from backend.core.project import project_manager, sanitize_name
from backend.core.timeutil import utc_iso_z, utc_now
from backend.schemas.pipeline_state import (
    ContextBudgetSnapshot,
    LLMConfigSnapshot,
    PipelineState,
    StepState,
)


PIPELINE_STATE_FILE = "pipeline_state.json"
STEP1_FILE = "step1_feature_points.json"
STEP2_FILE = "step2_cases_by_fp.json"
STEP3_FILE = "step3_merged_cases.json"
STEP4_FILE = "step4_validated_cases.json"
FINAL_CASES_FILE = "cases.json"
COVERAGE_MD_FILE = "coverage_report.md"
COVERAGE_JSON_FILE = "coverage_report.json"
TRACE_FILE = "generation_trace.json"


_PIPELINE_ID_RE = re.compile(r"^pl_\d{8}_\d{6}_[a-f0-9]{4}$")


# ============ id / 目录 =====================================================

def new_pipeline_id(now: Optional[datetime] = None) -> str:
    """生成 pl_<yyyymmdd>_<hhmmss>_<rand4>。"""
    now = now or utc_now()
    return f"pl_{now.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}"


def is_valid_pipeline_id(pid: str) -> bool:
    return bool(_PIPELINE_ID_RE.match(pid or ""))


def pipeline_dir(project: str, pipeline_id: str, *, create: bool = False) -> Path:
    """返回 outputs/testcases/<project>/<pipeline_id>/。

    Parameters
    ----------
    create : bool
        True 则按需 mkdir（创建新流水线时用）；False 只返回路径。
    """
    if not is_valid_pipeline_id(pipeline_id):
        raise ValueError(f"invalid pipeline_id: {pipeline_id!r}")
    base = project_manager.out_testcase_dir(project) / pipeline_id
    if create:
        base.mkdir(parents=True, exist_ok=True)
    return base


def list_pipelines(project: str) -> list[str]:
    """列出该项目下所有已存在的 pipeline_id，按 id 升序（= 时间升序）。"""
    base = project_manager.out_testcase_dir(sanitize_name(project))
    if not base.exists():
        return []
    pids = [
        p.name for p in base.iterdir()
        if p.is_dir() and is_valid_pipeline_id(p.name)
    ]
    return sorted(pids)


# ============ state 读写（原子） ============================================

def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def save_state(state: PipelineState) -> Path:
    """把 state 写到 <pipeline_dir>/pipeline_state.json。

    每次写前刷新 updated_at。
    """
    state.updated_at = utc_iso_z()
    d = pipeline_dir(state.project, state.pipeline_id, create=True)
    path = d / PIPELINE_STATE_FILE
    _atomic_write_json(path, state.model_dump(mode="json"))
    return path


def load_state(project: str, pipeline_id: str) -> PipelineState:
    path = pipeline_dir(project, pipeline_id) / PIPELINE_STATE_FILE
    if not path.exists():
        raise FileNotFoundError(f"pipeline not found: {project}/{pipeline_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return PipelineState.model_validate(data)


def create_state(
    project: str,
    question: str,
    *,
    llm_cfg: LLMConfigSnapshot,
    mentions: Optional[list[str]] = None,
    filters: Optional[dict] = None,
    context_budget: Optional[ContextBudgetSnapshot] = None,
    pipeline_id: Optional[str] = None,
) -> PipelineState:
    """创建一个全新 pipeline 的初始 state（step1_pending）。落盘后返回 state 对象。"""
    now = utc_iso_z()
    pid = pipeline_id or new_pipeline_id()
    if context_budget is None:
        cb = settings.context_budget
        context_budget = ContextBudgetSnapshot(
            per_call_max_tokens=cb.per_call_max_tokens,
            history_max_chars=cb.history_max_chars,
            retrieval_top_k_chunks=cb.retrieval_top_k_chunks,
            retrieval_top_k_kps=cb.retrieval_top_k_kps,
            step2_max_parallel=cb.step2_max_parallel,
        )
    state = PipelineState(
        pipeline_id=pid,
        project=sanitize_name(project),
        question=question,
        mentions=list(mentions or []),
        filters=dict(filters or {}),
        created_at=now,
        updated_at=now,
        current_step="step1_pending",
        steps={
            "step1": StepState(next_action="run_step_1"),
            "step2": StepState(),
            "step3": StepState(),
            "step4": StepState(),
        },
        llm_cfg_snapshot=llm_cfg,
        context_budget=context_budget,
    )
    save_state(state)
    return state


# ============ step 产物 json 读写 ============================================

def step_output_path(project: str, pipeline_id: str, step_n: int) -> Path:
    mapping = {1: STEP1_FILE, 2: STEP2_FILE, 3: STEP3_FILE, 4: STEP4_FILE}
    if step_n not in mapping:
        raise ValueError(f"step must be 1..4, got {step_n}")
    return pipeline_dir(project, pipeline_id) / mapping[step_n]


def write_step_output(project: str, pipeline_id: str, step_n: int, payload: dict) -> Path:
    path = step_output_path(project, pipeline_id, step_n)
    _atomic_write_json(path, payload)
    return path


def read_step_output(project: str, pipeline_id: str, step_n: int) -> Optional[dict]:
    path = step_output_path(project, pipeline_id, step_n)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ============ 状态转移辅助 ==================================================

def _fail_key(n: int) -> str:
    return f"failed_at_step{n}"


def transition_to_running(state: PipelineState, step_n: int) -> None:
    """state 切到 stepN_running 并记录 started_at。"""
    key = f"step{step_n}"
    state.steps[key].status = "running"
    state.steps[key].started_at = utc_iso_z()
    state.steps[key].error = None
    state.current_step = f"step{step_n}_running"  # type: ignore[assignment]


def transition_to_done(state: PipelineState, step_n: int, output_file: str) -> None:
    key = f"step{step_n}"
    s = state.steps[key]
    s.status = "done"
    s.completed_at = utc_iso_z()
    if s.started_at:
        try:
            t0 = datetime.fromisoformat(s.started_at.rstrip("Z"))
            t1 = datetime.fromisoformat(s.completed_at.rstrip("Z"))
            s.duration_ms = int((t1 - t0).total_seconds() * 1000)
        except ValueError:
            pass
    s.output_file = output_file
    # 整体 current_step：step4_done → "completed"
    state.current_step = "completed" if step_n == 4 else f"step{step_n}_done"  # type: ignore[assignment]


def transition_to_failed(state: PipelineState, step_n: int, err: str) -> None:
    key = f"step{step_n}"
    s = state.steps[key]
    s.status = "failed"
    s.error = err[:2000]
    s.completed_at = utc_iso_z()
    state.current_step = _fail_key(step_n)  # type: ignore[assignment]


def rollback_to(state: PipelineState, step_n: int) -> None:
    """回退到 stepN_pending。不删产物文件（用户可能对比），但会把更高步的 status 重置。"""
    if step_n not in (1, 2, 3, 4):
        raise ValueError("rollback step must be 1..4")
    state.current_step = f"step{step_n}_pending"  # type: ignore[assignment]
    for n in range(step_n, 5):
        s = state.steps[f"step{n}"]
        s.status = "pending"
        s.error = None
        s.started_at = None
        s.completed_at = None
        s.duration_ms = 0
        s.user_edited = False


def mark_user_edited(state: PipelineState, step_n: int) -> None:
    """用户编辑了 stepN 输出 → 标记后续步 pending（必须重跑）。"""
    key = f"step{step_n}"
    state.steps[key].user_edited = True
    state.steps[key].status = "user_edited_pending"
    for n in range(step_n + 1, 5):
        s = state.steps[f"step{n}"]
        s.status = "pending"
        s.output_file = None
    state.current_step = f"step{step_n}_done"  # type: ignore[assignment]
