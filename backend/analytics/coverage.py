"""覆盖率分析（CoverageAnalyzer）—— 测试用例对知识点的回链计算。

三级命中判定（docs/design/03 §7）：
  - explicit  (weight=1.0)：case.source_refs.kp_id == kp.kp_id
  - same_chunk(weight=0.7)：case.source_refs.chunk_id == kp.source.chunk_id
  - semantic  (weight=0.4)：case_embed · kp_embed ≥ sim_threshold
  每个 KP 取**最高 tier** 作为该 KP 的覆盖结果；没有任何命中 = uncovered (0.0)。

加权覆盖分 = Σ kp_weight / total_kps（介于 0 与 1 之间）。

产物：
  - coverage_report.json：结构化数据，前端用
  - coverage_report.md：人类可读的摘要（分模块、分类型）

不抛错：embedding 不可用时自动跳过 semantic tier，只用 explicit + same_chunk。
"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

from backend.core import embeddings as _emb_mod
from backend.schemas.knowledge_point import KnowledgePoint
from backend.schemas.test_case import TestCase


logger = logging.getLogger(__name__)


# 三级命中的权重
WEIGHT_EXPLICIT = 1.0
WEIGHT_SAME_CHUNK = 0.7
WEIGHT_SEMANTIC = 0.4
DEFAULT_SIM_THRESHOLD = 0.75

Tier = str  # "explicit" | "same_chunk" | "semantic" | "uncovered"


@dataclass
class KPCoverage:
    kp_id: str
    module: str
    type: str
    tier: Tier                         # 最高命中层级
    score: float                       # 对应权重（uncovered=0）
    matched_case_ids: list[str] = field(default_factory=list)
    best_similarity: Optional[float] = None  # 仅当 tier=semantic 时有值

    def to_dict(self) -> dict:
        return {
            "kp_id": self.kp_id,
            "module": self.module,
            "type": self.type,
            "tier": self.tier,
            "score": round(self.score, 4),
            "matched_case_ids": list(self.matched_case_ids),
            "best_similarity": (
                round(self.best_similarity, 4) if self.best_similarity is not None else None
            ),
        }


@dataclass
class CoverageReport:
    project: str
    pipeline_id: Optional[str]
    total_kps: int
    total_cases: int
    tier_counts: dict[str, int]            # tier -> count
    tier_ratios: dict[str, float]
    weighted_score: float                  # Σ score / total_kps
    by_kp: list[KPCoverage]
    by_module: dict[str, dict]             # module -> {total, covered, score}
    by_type: dict[str, dict]               # kp.type -> {total, covered, score}
    uncovered_kp_ids: list[str]
    sim_threshold: float
    semantic_skipped: bool = False         # embedding 不可用时 True

    def to_dict(self) -> dict:
        return {
            "project": self.project,
            "pipeline_id": self.pipeline_id,
            "total_kps": self.total_kps,
            "total_cases": self.total_cases,
            "tier_counts": dict(self.tier_counts),
            "tier_ratios": {k: round(v, 4) for k, v in self.tier_ratios.items()},
            "weighted_score": round(self.weighted_score, 4),
            "uncovered_kp_ids": list(self.uncovered_kp_ids),
            "sim_threshold": self.sim_threshold,
            "semantic_skipped": self.semantic_skipped,
            "by_kp": [k.to_dict() for k in self.by_kp],
            "by_module": self.by_module,
            "by_type": self.by_type,
        }


# ============ 主入口 ========================================================

def compute(
    cases: Iterable[TestCase],
    kps: Iterable[KnowledgePoint],
    *,
    project: str,
    pipeline_id: Optional[str] = None,
    sim_threshold: float = DEFAULT_SIM_THRESHOLD,
    enable_semantic: bool = True,
) -> CoverageReport:
    """计算 cases 对 kps 的覆盖报告。

    Parameters
    ----------
    cases, kps : 待分析的用例与知识点（可为空）
    sim_threshold : semantic tier 的余弦相似度阈值
    enable_semantic : False 时不调 embedding（加速 / 避免加载 BGE）
    """
    cases = list(cases)
    kps = list(kps)
    if not kps:
        return _empty_report(project, pipeline_id, sim_threshold, len(cases))

    # 预备索引
    kp_by_id = {kp.kp_id: kp for kp in kps}
    kp_by_chunk: dict[str, list[str]] = defaultdict(list)
    for kp in kps:
        kp_by_chunk[kp.source.chunk_id].append(kp.kp_id)

    # 每个 KP 的临时命中记录
    hits: dict[str, dict] = {
        kp.kp_id: {
            "tier": "uncovered",
            "score": 0.0,
            "matched": set(),           # case_ids
            "best_sim": None,
        } for kp in kps
    }

    # ---- Tier 1：explicit ----------------------------------------------------
    # ---- Tier 2：same_chunk --------------------------------------------------
    for tc in cases:
        for ref in tc.source_refs:
            if ref.kp_id and ref.kp_id in kp_by_id:
                _upgrade(hits, ref.kp_id, "explicit", WEIGHT_EXPLICIT, tc.case_id)
            if ref.chunk_id:
                for kid in kp_by_chunk.get(ref.chunk_id, ()):
                    _upgrade(hits, kid, "same_chunk", WEIGHT_SAME_CHUNK, tc.case_id)

    # ---- Tier 3：semantic ----------------------------------------------------
    semantic_skipped = False
    if enable_semantic and cases:
        try:
            kp_vecs = _emb_mod.embed([_kp_embed_text(kp) for kp in kps])
            case_vecs = _emb_mod.embed([_case_embed_text(tc) for tc in cases])
            # cosine (已 normalize)
            sims = case_vecs @ kp_vecs.T            # shape: (n_cases, n_kps)
            for j, kp in enumerate(kps):
                # 只给当前 tier 低于 semantic 的 KP 升级
                if hits[kp.kp_id]["tier"] in ("explicit", "same_chunk"):
                    continue
                col = sims[:, j]
                best_idx = int(np.argmax(col))
                best_sim = float(col[best_idx])
                if best_sim >= sim_threshold:
                    _upgrade(
                        hits, kp.kp_id, "semantic", WEIGHT_SEMANTIC,
                        cases[best_idx].case_id,
                    )
                    hits[kp.kp_id]["best_sim"] = best_sim
        except Exception as e:  # noqa: BLE001
            logger.warning("[coverage] embedding 不可用，跳过 semantic tier: %r", e)
            semantic_skipped = True

    # ---- 汇总 ---------------------------------------------------------------
    by_kp: list[KPCoverage] = []
    tier_counter: Counter[str] = Counter()
    total_weight = 0.0
    uncovered: list[str] = []
    module_agg: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "covered": 0, "score_sum": 0.0})
    type_agg: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "covered": 0, "score_sum": 0.0})

    for kp in kps:
        h = hits[kp.kp_id]
        tier = h["tier"]
        score = h["score"]
        tier_counter[tier] += 1
        total_weight += score
        if tier == "uncovered":
            uncovered.append(kp.kp_id)
        by_kp.append(KPCoverage(
            kp_id=kp.kp_id, module=kp.module, type=kp.type,
            tier=tier, score=score,
            matched_case_ids=sorted(h["matched"]),
            best_similarity=h["best_sim"],
        ))
        module_agg[kp.module]["total"] += 1
        type_agg[kp.type]["total"] += 1
        if tier != "uncovered":
            module_agg[kp.module]["covered"] += 1
            type_agg[kp.type]["covered"] += 1
        module_agg[kp.module]["score_sum"] += score
        type_agg[kp.type]["score_sum"] += score

    n = len(kps)
    tier_ratios = {k: v / n for k, v in tier_counter.items()}
    # 补齐四档（即便 0 也展示）
    for k in ("explicit", "same_chunk", "semantic", "uncovered"):
        tier_counter.setdefault(k, 0)
        tier_ratios.setdefault(k, 0.0)

    by_module = {
        m: {
            "total": v["total"],
            "covered": v["covered"],
            "score": round(v["score_sum"] / v["total"], 4) if v["total"] else 0.0,
        }
        for m, v in module_agg.items()
    }
    by_type = {
        t: {
            "total": v["total"],
            "covered": v["covered"],
            "score": round(v["score_sum"] / v["total"], 4) if v["total"] else 0.0,
        }
        for t, v in type_agg.items()
    }

    return CoverageReport(
        project=project, pipeline_id=pipeline_id,
        total_kps=n, total_cases=len(cases),
        tier_counts=dict(tier_counter),
        tier_ratios=tier_ratios,
        weighted_score=total_weight / n,
        by_kp=by_kp,
        by_module=by_module,
        by_type=by_type,
        uncovered_kp_ids=uncovered,
        sim_threshold=sim_threshold,
        semantic_skipped=semantic_skipped,
    )


def _empty_report(project: str, pipeline_id: Optional[str],
                  sim_threshold: float, total_cases: int) -> CoverageReport:
    return CoverageReport(
        project=project, pipeline_id=pipeline_id,
        total_kps=0, total_cases=total_cases,
        tier_counts={"explicit": 0, "same_chunk": 0, "semantic": 0, "uncovered": 0},
        tier_ratios={"explicit": 0.0, "same_chunk": 0.0, "semantic": 0.0, "uncovered": 0.0},
        weighted_score=0.0,
        by_kp=[], by_module={}, by_type={},
        uncovered_kp_ids=[], sim_threshold=sim_threshold,
    )


def _upgrade(hits: dict, kp_id: str, tier: str, weight: float, case_id: str) -> None:
    """只在新 tier 的 weight 更高时替换 tier/score；无论如何都追加 case_id。"""
    h = hits[kp_id]
    if weight > h["score"]:
        h["tier"] = tier
        h["score"] = weight
        h["matched"] = {case_id}        # 升级时只保留当前层级的 case
    elif weight == h["score"] and h["tier"] == tier:
        h["matched"].add(case_id)


# ============ embedding 文本 ================================================

def _kp_embed_text(kp: KnowledgePoint) -> str:
    return f"[{kp.type}/{kp.module}] {kp.content}"


def _case_embed_text(tc: TestCase) -> str:
    actions = " ".join(s.action for s in tc.steps)
    return f"{tc.title} | {tc.category} | {actions} | {tc.expected_result}"


# ============ 渲染 / 保存 ===================================================

def render_markdown(report: CoverageReport) -> str:
    lines: list[str] = []
    lines.append(f"# 覆盖率报告 · {report.project}")
    if report.pipeline_id:
        lines.append(f"_pipeline_: `{report.pipeline_id}`")
    lines.append("")
    lines.append(f"- 总 KP 数: **{report.total_kps}**")
    lines.append(f"- 总用例数: **{report.total_cases}**")
    lines.append(f"- 加权覆盖分: **{report.weighted_score:.2%}**")
    if report.semantic_skipped:
        lines.append("- ⚠️ 语义 tier 被跳过（embedding 不可用）")
    lines.append("")
    lines.append("## 覆盖层级分布")
    lines.append("| 层级 | 数量 | 占比 |")
    lines.append("|---|---:|---:|")
    for k in ("explicit", "same_chunk", "semantic", "uncovered"):
        c = report.tier_counts.get(k, 0)
        r = report.tier_ratios.get(k, 0.0)
        lines.append(f"| {k} | {c} | {r:.2%} |")
    lines.append("")

    if report.by_module:
        lines.append("## 模块维度")
        lines.append("| 模块 | KP 数 | 已覆盖 | 加权分 |")
        lines.append("|---|---:|---:|---:|")
        for m in sorted(report.by_module):
            v = report.by_module[m]
            lines.append(f"| {m} | {v['total']} | {v['covered']} | {v['score']:.2%} |")
        lines.append("")

    if report.by_type:
        lines.append("## 类型维度")
        lines.append("| 类型 | KP 数 | 已覆盖 | 加权分 |")
        lines.append("|---|---:|---:|---:|")
        for t in sorted(report.by_type):
            v = report.by_type[t]
            lines.append(f"| {t} | {v['total']} | {v['covered']} | {v['score']:.2%} |")
        lines.append("")

    if report.uncovered_kp_ids:
        lines.append("## 未覆盖 KP")
        for kid in report.uncovered_kp_ids[:100]:
            lines.append(f"- `{kid}`")
        if len(report.uncovered_kp_ids) > 100:
            lines.append(f"- ...（另有 {len(report.uncovered_kp_ids) - 100} 条省略）")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def save(report: CoverageReport, output_dir: Path,
         *, md_name: str = "coverage_report.md",
         json_name: str = "coverage_report.json") -> tuple[Path, Path]:
    """把报告写到 output_dir 下。返回 (md_path, json_path)。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / md_name
    json_path = output_dir / json_name

    md_tmp = md_path.with_suffix(md_path.suffix + ".tmp")
    md_tmp.write_text(render_markdown(report), encoding="utf-8")
    md_tmp.replace(md_path)

    json_tmp = json_path.with_suffix(json_path.suffix + ".tmp")
    json_tmp.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    json_tmp.replace(json_path)
    return md_path, json_path
