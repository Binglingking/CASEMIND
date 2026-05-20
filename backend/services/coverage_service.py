"""CoverageAnalyzer 的服务层 —— 从 pipeline 产物 + 当前 KP 计算 & 读取覆盖率报告。

职责：
  - 路由只认 dict；这里负责加载 cases / KP、调 analytics.coverage.compute、落盘
  - read_cached 用于 GET 快速回读，避免重复计算
  - 不做 feature-flag 检查（留给路由层）
"""
from __future__ import annotations

import json
from typing import Optional

from backend.agents.case_gen import pipeline_io
from backend.analytics import coverage as cov_mod
from backend.core import kp_store
from backend.schemas.test_case import TestCase


def compute_and_save(project: str, pipeline_id: str, *,
                     sim_threshold: float = 0.75,
                     enable_semantic: bool = True) -> dict:
    """从 pipeline 的最终 cases.json + 当前 KP 计算覆盖率，落盘并返回 dict。"""
    d = pipeline_io.pipeline_dir(project, pipeline_id)
    cases_path = d / pipeline_io.FINAL_CASES_FILE
    if not cases_path.exists():
        raise FileNotFoundError(
            f"{pipeline_io.FINAL_CASES_FILE} 不存在，请先跑完整条 pipeline（step4 产生最终用例）"
        )
    data = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = [TestCase.model_validate(c) for c in data.get("cases", [])]

    kps = kp_store.load_all(project)
    report = cov_mod.compute(
        cases, kps,
        project=project, pipeline_id=pipeline_id,
        sim_threshold=sim_threshold, enable_semantic=enable_semantic,
    )
    cov_mod.save(report, d)
    return report.to_dict()


def read_cached(project: str, pipeline_id: str) -> Optional[dict]:
    d = pipeline_io.pipeline_dir(project, pipeline_id)
    p = d / pipeline_io.COVERAGE_JSON_FILE
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def list_summaries(project: str) -> list[dict]:
    """列出该项目下所有已计算出覆盖率的 pipeline 摘要，按 pipeline_id 升序。"""
    out: list[dict] = []
    for pid in pipeline_io.list_pipelines(project):
        d = pipeline_io.pipeline_dir(project, pid)
        p = d / pipeline_io.COVERAGE_JSON_FILE
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({
            "pipeline_id": pid,
            "total_kps": data.get("total_kps"),
            "total_cases": data.get("total_cases"),
            "weighted_score": data.get("weighted_score"),
            "semantic_skipped": data.get("semantic_skipped"),
        })
    return out
