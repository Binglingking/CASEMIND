"""增量分析缓存管理。

记录已分析的用例和XMind节点的指纹，支持跳过已处理的项。
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from backend.core.project import project_manager


logger = logging.getLogger(__name__)


class AnalysisCacheEntry(BaseModel):
    """单个分析缓存条目。"""
    item_id: str                    # case_id 或 node_id
    fingerprint: str                # 内容hash
    analyzed_at: str               # ISO8601时间戳
    stage2_signals_count: int = 0  # Stage 2提取的信号数量


class AnalysisCache(BaseModel):
    """项目的分析缓存。"""
    project: str
    version: int = 1
    cases: dict[str, AnalysisCacheEntry] = Field(default_factory=dict)
    xmind_nodes: dict[str, AnalysisCacheEntry] = Field(default_factory=dict)
    last_full_analysis: Optional[str] = None  # 最后一次完整分析的时间


def _cache_path(project: str) -> Path:
    """获取缓存文件路径。"""
    return project_manager.mem_dir(project) / "legacy" / "analysis_cache.json"


def load_cache(project: str) -> AnalysisCache:
    """加载分析缓存。"""
    path = _cache_path(project)
    if not path.exists():
        return AnalysisCache(project=project)
    
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AnalysisCache.model_validate(data)
    except Exception as e:
        logger.warning(f"[AnalysisCache] 加载缓存失败: {e}，使用空缓存")
        return AnalysisCache(project=project)


def save_cache(project: str, cache: AnalysisCache) -> None:
    """保存分析缓存。"""
    path = _cache_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cache.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def compute_fingerprint(content: str) -> str:
    """计算内容的SHA256指纹。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def is_case_analyzed(cache: AnalysisCache, case_id: str, content: str) -> bool:
    """检查用例是否已分析且内容未变化。"""
    if case_id not in cache.cases:
        return False
    
    entry = cache.cases[case_id]
    current_fp = compute_fingerprint(content)
    return entry.fingerprint == current_fp


def is_xmind_node_analyzed(cache: AnalysisCache, node_id: str, content: str) -> bool:
    """检查XMind节点是否已分析且内容未变化。"""
    if node_id not in cache.xmind_nodes:
        return False
    
    entry = cache.xmind_nodes[node_id]
    current_fp = compute_fingerprint(content)
    return entry.fingerprint == current_fp


def mark_case_analyzed(
    cache: AnalysisCache,
    case_id: str,
    content: str,
    signals_count: int = 0,
    analyzed_at: str = "",
) -> None:
    """标记用例为已分析。"""
    from backend.core.timeutil import utc_iso_z
    
    cache.cases[case_id] = AnalysisCacheEntry(
        item_id=case_id,
        fingerprint=compute_fingerprint(content),
        analyzed_at=analyzed_at or utc_iso_z(),
        stage2_signals_count=signals_count,
    )


def mark_xmind_node_analyzed(
    cache: AnalysisCache,
    node_id: str,
    content: str,
    signals_count: int = 0,
    analyzed_at: str = "",
) -> None:
    """标记XMind节点为已分析。"""
    from backend.core.timeutil import utc_iso_z
    
    cache.xmind_nodes[node_id] = AnalysisCacheEntry(
        item_id=node_id,
        fingerprint=compute_fingerprint(content),
        analyzed_at=analyzed_at or utc_iso_z(),
        stage2_signals_count=signals_count,
    )


def get_unanalyzed_cases(
    cache: AnalysisCache,
    case_ids: list[str],
    case_contents: dict[str, str],  # case_id -> content
) -> list[str]:
    """获取未分析或用例内容有变化的case_id列表。"""
    unanalyzed = []
    for case_id in case_ids:
        content = case_contents.get(case_id, "")
        if not is_case_analyzed(cache, case_id, content):
            unanalyzed.append(case_id)
    return unanalyzed


def get_unanalyzed_xmind_nodes(
    cache: AnalysisCache,
    node_ids: list[str],
    node_contents: dict[str, str],  # node_id -> content
) -> list[str]:
    """获取未分析或内容有变化的XMind节点ID列表。"""
    unanalyzed = []
    for node_id in node_ids:
        content = node_contents.get(node_id, "")
        if not is_xmind_node_analyzed(cache, node_id, content):
            unanalyzed.append(node_id)
    return unanalyzed


def clear_cache(project: str) -> None:
    """清空项目的分析缓存（用于强制完全重建）。"""
    path = _cache_path(project)
    if path.exists():
        path.unlink()
    logger.info(f"[AnalysisCache] 已清空项目 {project} 的分析缓存")


def get_cache_stats(cache: AnalysisCache) -> dict:
    """获取缓存统计信息。"""
    return {
        "project": cache.project,
        "cached_cases": len(cache.cases),
        "cached_xmind_nodes": len(cache.xmind_nodes),
        "last_full_analysis": cache.last_full_analysis,
    }
