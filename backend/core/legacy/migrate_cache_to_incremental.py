"""迁移工具：从已有反哺候选初始化分析缓存。

用途：在启用增量分析前，将历史分析结果导入缓存，避免重复分析。

使用方法：
    python -m backend.core.legacy.migrate_cache_to_incremental <project>
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.core.legacy.analysis_cache import (
    AnalysisCache,
    load_cache,
    save_cache,
    mark_case_analyzed,
    mark_xmind_node_analyzed,
)
from backend.core.legacy.legacy_store import load_inferred_kps, all_cases, load_xmind_tree, list_xmind_files
from backend.core.timeutil import utc_iso_z


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


def migrate_project(project: str) -> None:
    """将项目的反哺候选转换为分析缓存。"""
    logger.info(f"[Migrate] 开始迁移项目: {project}")
    
    # 加载现有缓存（可能为空）
    cache = load_cache(project)
    
    # 加载所有反哺候选
    inferred_kps = load_inferred_kps(project)
    logger.info(f"[Migrate] 找到 {len(inferred_kps)} 个反哺候选")
    
    if not inferred_kps:
        logger.warning(f"[Migrate] 项目 {project} 没有反哺候选，无法迁移")
        logger.info(f"[Migrate] 建议：先运行一次完整分析生成反哺候选")
        return
    
    # 加载所有用例（用于构建内容指纹）
    all_legacy_cases = all_cases(project)
    case_map = {c.case_id: c for c in all_legacy_cases}
    logger.info(f"[Migrate] 找到 {len(case_map)} 个历史用例")
    
    # 加载所有XMind树（用于构建节点内容指纹）
    xmind_files = list_xmind_files(project)
    xmind_node_map = {}  # node_id -> (title, path, note)
    for xf in xmind_files:
        tree = load_xmind_tree(project, xf['file_id'])
        if tree:
            # 构建node_id到节点信息的映射
            for node in tree.nodes:
                # 使用与stage2_extract.py完全相同的格式
                # leaf.path 是从根到自身的完整路径（含自身title）
                xmind_node_map[node.node_id] = (
                    node.title,
                    node.path,  # 完整的path列表
                    node.note or ""
                )
    logger.info(f"[Migrate] 找到 {len(xmind_node_map)} 个XMind节点信息")
    
    # 统计
    migrated_cases = set()
    migrated_nodes = set()
    skipped = 0
    
    # 遍历反哺候选，提取source信息
    for kp in inferred_kps:
        analyzed_at = kp.extracted_at or utc_iso_z()
        
        if kp.source.kind == "case":
            # 用例来源
            case_id = kp.source.case_id
            if not case_id:
                skipped += 1
                continue
            
            # 从用例数据构建内容指纹
            legacy_case = case_map.get(case_id)
            if legacy_case:
                content = f"{legacy_case.title}|{legacy_case.preconditions}|{str([(s.action, s.expected) for s in legacy_case.steps])}"
                mark_case_analyzed(cache, case_id, content, signals_count=1, analyzed_at=analyzed_at)
                migrated_cases.add(case_id)
            else:
                # 如果找不到用例，用简单方式标记
                mark_case_analyzed(cache, case_id, f"case:{case_id}", signals_count=1, analyzed_at=analyzed_at)
                migrated_cases.add(case_id)
                
        elif kp.source.kind == "xmind":
            # XMind来源
            node_id = kp.source.node_id
            if not node_id:
                skipped += 1
                continue
            
            # 从XMind树中获取节点信息，使用与Stage 2相同的格式
            if node_id in xmind_node_map:
                title, path, note = xmind_node_map[node_id]
                # 使用与stage2_extract.py第311行完全相同的格式
                content = f"{title}|{'/'.join(path)}|{note}"
                mark_xmind_node_analyzed(cache, node_id, content, signals_count=1, analyzed_at=analyzed_at)
                migrated_nodes.add(node_id)
            else:
                # 如果找不到节点信息，跳过
                logger.debug(f"[Migrate] 未找到XMind节点 {node_id} 的信息")
                skipped += 1
    
    # 保存缓存
    cache.last_full_analysis = utc_iso_z()
    save_cache(project, cache)
    
    # 输出统计
    logger.info(f"[Migrate] 迁移完成！")
    logger.info(f"[Migrate]   - 已迁移用例: {len(migrated_cases)} 个")
    logger.info(f"[Migrate]   - 已迁移XMind节点: {len(migrated_nodes)} 个")
    logger.info(f"[Migrate]   - 跳过无效项: {skipped} 个")
    logger.info(f"[Migrate]   - 缓存文件: memory/{project}/legacy/analysis_cache.json")
    logger.info(f"[Migrate]")
    logger.info(f"[Migrate] 下次运行增量分析时，这些项将被自动跳过！")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python -m backend.core.legacy.migrate_cache_to_incremental <project>")
        print("示例: python -m backend.core.legacy.migrate_cache_to_incremental 投放管理平台")
        sys.exit(1)
    
    project_name = sys.argv[1]
    migrate_project(project_name)
