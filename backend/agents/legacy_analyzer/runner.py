"""legacy_analyzer 五阶段编排。

调用顺序：
  1. stage1_normalize.normalize(project)
  2. stage2_extract.extract(batch, ...)            ← 唯一调 LLM
  3. stage3_style.compute_style(project, batch)
  4. stage4_aggregate.aggregate(signals)
  5. stage5_inferred.to_inferred_kps(aggregated, batch) + persist

副作用（落盘）：
  - memory/<project>/legacy/style_profile.json
  - memory/<project>/legacy/inferred_kps.json     （pending）
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from backend.agents.legacy_analyzer import (
    stage1_normalize,
    stage2_extract,
    stage3_style,
    stage4_aggregate,
    stage5_inferred,
)
from backend.agents.legacy_analyzer.progress_tracker import controller_manager
from backend.agents.legacy_analyzer.schemas import AnalyzerRunResult
from backend.core.legacy import legacy_store
from backend.core.llm import LLMConfig
from backend.core.timeutil import utc_iso_z
from backend.schemas.style_profile import (
    CaseStyle,
    StyleProfile,
    XMindStyle,
)


logger = logging.getLogger(__name__)


def _read_features():
    try:
        from backend.api.routes_settings import get_runtime_features
        return get_runtime_features()
    except Exception:  # noqa: BLE001
        from backend.config import settings
        return settings.features


def run(
    project: str,
    *,
    cfg: LLMConfig,
    chat_fn: Optional[stage2_extract.ChatFn] = None,
    skip_extract: bool = False,
    incremental: bool = False,  # 新增：是否启用增量分析
) -> AnalyzerRunResult:
    """跑全部五阶段。

    Parameters
    ----------
    skip_extract : bool
        True 时跳过 Stage 2（不调 LLM）。仅做风格画像更新；用于离线初始化。
    incremental : bool
        True 时只分析未处理过或内容有变化的用例/XMind
    """
    # 获取或创建控制器
    controller = controller_manager.get_or_create(project)
    controller.start()
    
    start_time = time.time()
    logger.info(f"[Legacy Analyzer] 开始五阶段分析，项目: {project}")
    
    try:
        # Stage 1: Normalize
        controller.update_progress(stage=1, stage_name="标准化数据", message="正在加载用例和XMind数据...")
        logger.info("[Stage 1] 开始标准化数据...")
        stage1_start = time.time()
        batch = stage1_normalize.normalize(project)
        stage1_elapsed = time.time() - stage1_start
        logger.info(f"[Stage 1] 完成，耗时 {stage1_elapsed:.1f}s，用例 {len(batch.case_units)} 个，XMind叶子 {len(batch.xmind_leaves)} 个")
        controller.update_progress(
            completed_batches=1,
            message=f"Stage 1 完成 ({stage1_elapsed:.1f}s)"
        )

        # Stage 2: Extract (LLM)
        extracted = []
        llm_calls = 0
        errors: list[str] = []
        
        if not skip_extract:
            controller.update_progress(
                stage=2,
                stage_name="信号抽取（LLM）",
                message="开始调用LLM进行信号抽取..."
            )
            logger.info("[Stage 2] 开始信号抽取（调用LLM）...")
            stage2_start = time.time()
            
            # 传入controller以便在extract中更新进度
            extracted, llm_calls, errors = stage2_extract.extract(
                batch, cfg=cfg, chat_fn=chat_fn, controller=controller,
                incremental=incremental,  # 传递增量分析标志
            )
            
            stage2_elapsed = time.time() - stage2_start
            logger.info(f"[Stage 2] 完成，耗时 {stage2_elapsed:.1f}s，LLM调用 {llm_calls} 次，提取 {len(extracted)} 个信号")
            controller.update_progress(
                completed_batches=2,
                llm_calls=llm_calls,
                extracted_signals=len(extracted),
                message=f"Stage 2 完成 ({stage2_elapsed:.1f}s)"
            )
        else:
            logger.info("[Stage 2] 跳过（skip_extract=True）")
            controller.update_progress(stage=2, stage_name="信号抽取（已跳过）")

        # 检查是否取消
        if controller.is_cancelled():
            logger.info("[Legacy Analyzer] 分析已取消")
            controller.complete()
            raise RuntimeError("分析已被用户取消")

        # Stage 3: Style
        controller.update_progress(stage=3, stage_name="计算风格画像", message="正在分析用例风格...")
        logger.info("[Stage 3] 计算风格画像...")
        stage3_start = time.time()
        style_stats = stage3_style.compute_style(project, batch)
        stage3_elapsed = time.time() - stage3_start
        logger.info(f"[Stage 3] 完成，耗时 {stage3_elapsed:.1f}s")
        controller.update_progress(
            completed_batches=3,
            message=f"Stage 3 完成 ({stage3_elapsed:.1f}s)"
        )

        # Stage 4: Aggregate
        controller.update_progress(stage=4, stage_name="聚合信号", message="正在聚合提取的信号...")
        logger.info("[Stage 4] 聚合信号...")
        stage4_start = time.time()
        aggregated = stage4_aggregate.aggregate(extracted)
        stage4_elapsed = time.time() - stage4_start
        logger.info(f"[Stage 4] 完成，耗时 {stage4_elapsed:.1f}s，聚合 {len(aggregated.items)} 个规则")
        controller.update_progress(
            completed_batches=4,
            message=f"Stage 4 完成 ({stage4_elapsed:.1f}s)"
        )

        # Stage 4.5: AI 智能归纳 + Stage 5: 生成反哺候选
        # 使用 AI 归纳模式（summarize_signals）来合并去重、生成高价值知识点；
        # 仅在 skip_extract=True 时回退到原始 1:1 转换模式。
        controller.update_progress(stage=5, stage_name="AI 归纳与反哺候选",
                                   message="正在调用 LLM 进行全局归纳...")
        logger.info("[Stage 4.5] AI 归纳反哺候选...")
        stage5_start = time.time()
        summarize_errors: list[str] = []
        features = _read_features()
        if not getattr(features, "enable_legacy_inference", False):
            inferred = []
            logger.info("[Stage 5] legacy inference disabled; skip inferred KP generation")
        elif not skip_extract and aggregated.items:
            # AI 归纳模式
            inferred, summarize_calls, summarize_errors = stage5_inferred.summarize_signals(
                aggregated, batch, cfg=cfg,
                auto_accept=getattr(features, "enable_legacy_inference_auto_accept", False),
            )
            llm_calls += summarize_calls
            errors.extend(summarize_errors)
            logger.info(
                "[Stage 4.5] AI 归纳完成，LLM 调用 %d 次，"
                "%d 条信号 → %d 条知识点",
                summarize_calls, len(aggregated.items), len(inferred),
            )
        else:
            # 原始模式（1:1 转换，不调 LLM）
            inferred = stage5_inferred.to_inferred_kps(aggregated, batch)
            logger.info(
                "[Stage 5] 原始模式: %d 条信号 → %d 条知识点",
                len(aggregated.items), len(inferred),
            )

        if inferred:
            stage5_inferred.persist(project, inferred)
        stage5_elapsed = time.time() - stage5_start

        # 统计 auto_accepted 数量
        auto_count = sum(1 for ikp in inferred if ikp.review_status == "ready_to_build")
        pending_count = sum(1 for ikp in inferred if ikp.review_status in ("pending_review", "pending"))
        file_summary_count = len([ikp for ikp in inferred if ikp.aggregated_from])
        logger.info(
            f"[Stage 5] 完成，耗时 {stage5_elapsed:.1f}s，生成 {len(inferred)} 个反哺候选 "
            f"(auto_accepted={auto_count}, pending={pending_count})"
        )
        controller.update_progress(
            completed_batches=5,
            message=f"Stage 5 完成 ({stage5_elapsed:.1f}s, 自动通过 {auto_count}, 待审 {pending_count})"
        )

        # Save style profile
        profile = StyleProfile(
            project=project,
            generated_at=utc_iso_z(),
            case_style=CaseStyle(
                total_cases=style_stats.total_cases,
                title_scenario_expected_ratio=style_stats.title_scenario_expected_ratio,
                avg_steps_per_case=style_stats.avg_steps_per_case,
                avg_expected_per_case=style_stats.avg_expected_per_case,
                steps_expected_aligned_ratio=style_stats.steps_expected_aligned_ratio,
                stage_distribution=style_stats.stage_distribution,
                priority_distribution=style_stats.priority_distribution,
                case_type_distribution=style_stats.case_type_distribution,
                common_assertion_starts=style_stats.common_assertion_starts,
                common_action_verbs=style_stats.common_action_verbs,
            ),
            xmind_style=XMindStyle(
                total_trees=style_stats.total_trees,
                total_nodes=style_stats.total_nodes,
                avg_depth=style_stats.avg_depth,
                max_depth=style_stats.max_depth,
                avg_branching=style_stats.avg_branching,
                leaf_avg_chars=style_stats.leaf_avg_chars,
            ),
        )
        legacy_store.save_style_profile(project, profile)
        
        # ✅ 标记所有用例文件和XMind文件为已分析
        analyzed_at = utc_iso_z()  # 使用顶部已导入的函数
        
        # 更新用例文件标记
        for case_file in legacy_store.list_case_files(project):
            case_file.analyzed = True
            case_file.analyzed_at = analyzed_at
            legacy_store.upsert_case_file(project, case_file, legacy_store.load_cases(project, case_file.file_id))
        
        # 更新XMind文件标记
        for xmind_file in legacy_store.list_xmind_files(project):
            tree = legacy_store.load_xmind_tree(project, xmind_file['file_id'])
            if tree:
                tree.analyzed = True
                tree.analyzed_at = analyzed_at
                legacy_store.upsert_xmind_tree(project, tree)

        total_elapsed = time.time() - start_time
        logger.info(f"[Legacy Analyzer] 全部完成！总耗时 {total_elapsed:.1f}s ({total_elapsed/60:.1f}分钟)")
        controller.complete()

        return AnalyzerRunResult(
            project=project,
            case_units_count=len(batch.case_units),
            xmind_leaves_count=len(batch.xmind_leaves),
            xmind_mid_count=len(batch.xmind_mid_nodes),
            llm_calls=llm_calls,
            extracted_count=len(extracted),
            aggregated_count=len(aggregated.items),
            style_stats=style_stats,
            inferred_count=len(inferred),
            pending_review_count=pending_count,
            ready_to_build_count=auto_count,
            file_summary_count=file_summary_count,
            errors=errors,
        )
    
    except Exception as e:
        logger.error(f"[Legacy Analyzer] 分析失败: {e}")
        controller.complete(error=str(e))
        raise
