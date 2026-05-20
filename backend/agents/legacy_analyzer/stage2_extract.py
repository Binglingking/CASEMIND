"""Stage 2：信号抽取（唯一调 LLM 的阶段）。

策略：
  - 用例与 XMind 叶子各自分批，单批送 LLM
  - chat_fn 可注入，便于测试 mock
  - 任何一批失败只影响该批，不阻断（错误进 errors 列表）
  - LLM 给出的 source_ref 必须落在本批输入内，否则丢弃 + 计入丢弃
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from backend.agents.base import load_prompt
from backend.agents.legacy_analyzer.schemas import (
    ExtractBatchOutput,
    ExtractedSignal,
    NormalizedBatch,
    NormalizedCaseUnit,
    NormalizedXMindLeaf,
)
from backend.core import llm as _llm_mod
from backend.core.llm import LLMConfig, SchemaValidationError, parse_with_schema


logger = logging.getLogger(__name__)


# 单批容量上限（防 prompt 超长）
# 优化后：从8/20提升到25/50，减少约65%的LLM调用次数
CASE_BATCH_SIZE = 25
LEAF_BATCH_SIZE = 50

DEFAULT_SYSTEM = (
    "你是测试资产逆向分析师，擅长从历史用例和测试点脑图反推隐性业务规则。"
    "只输出合法 JSON，不要 Markdown 围栏、不要解释。"
)


# ---------- prompt 拼装 ----------

def _format_case(c: NormalizedCaseUnit) -> str:
    pairs = "\n".join(
        f"    {i + 1}. 操作: {a or '(无)'}\n       预期: {e or '(无)'}"
        for i, (a, e) in enumerate(c.step_pairs)
    ) or "    (无步骤)"
    return (
        f"- case_id: {c.case_id}\n"
        f"  module: {c.module}    sub_item: {c.sub_item_base}    stage: {c.stage or '(无)'}\n"
        f"  title: {c.title}\n"
        f"  preconditions: {c.preconditions or '(无)'}\n"
        f"  steps:\n{pairs}\n"
    )


def _format_leaf(n: NormalizedXMindLeaf) -> str:
    sibs = " / ".join(n.siblings) if n.siblings else "(无)"
    note = f"  note: {n.note}\n" if n.note else ""
    return (
        f"- node_id: {n.node_id}\n"
        f"  path: {' / '.join(n.path)}\n"
        f"  title: {n.title}\n"
        f"  siblings: {sibs}\n"
        f"{note}"
    )


def _build_user_prompt(
    cases: list[NormalizedCaseUnit],
    leaves: list[NormalizedXMindLeaf],
) -> str:
    parts = ["## 历史用例（本批次）"]
    parts.extend(_format_case(c) for c in cases) if cases else parts.append("(无)")
    parts.append("\n## XMind 叶子节点（本批次）")
    parts.extend(_format_leaf(n) for n in leaves) if leaves else parts.append("(无)")
    parts.append(
        "\n现在请从上面输入中反推隐性规则，输出 JSON。"
        "source_ref 必须严格取自本批次的 case_id 或 node_id。"
    )
    return "\n".join(parts)


# ---------- 单批调用 ----------

ChatFn = Callable[[list[dict], LLMConfig], str]


def _default_chat(messages: list[dict], cfg: LLMConfig) -> str:
    return _llm_mod.chat(
        messages=messages, cfg=cfg,
        temperature=0.2, json_mode=True,
    )


def _run_batch(
    cases: list[NormalizedCaseUnit],
    leaves: list[NormalizedXMindLeaf],
    *,
    cfg: LLMConfig,
    chat_fn: ChatFn,
) -> tuple[list[ExtractedSignal], int, Optional[str]]:
    """返回 (本批合法信号, 调用次数, 错误信息)。"""
    if not cases and not leaves:
        return [], 0, None

    sys_prompt = load_prompt("legacy/02_extract_signals.txt") or DEFAULT_SYSTEM
    user_prompt = _build_user_prompt(cases, leaves)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw = chat_fn(messages, cfg)
    except Exception as e:
        return [], 0, f"LLM 调用失败: {e!r}"

    try:
        parsed = parse_with_schema(
            raw, ExtractBatchOutput,
            retry_cfg=cfg, retry_messages=messages, max_retries=1,
        )
    except SchemaValidationError as e:
        return [], 1, f"Schema 校验失败: {e}"

    # 校验 source_ref 是否落在本批
    allowed_case_ids = {c.case_id for c in cases}
    allowed_node_ids = {n.node_id for n in leaves}
    valid: list[ExtractedSignal] = []
    for it in parsed.items:
        if it.confidence < 0.5:
            continue
        if it.source_kind == "case" and it.source_ref in allowed_case_ids:
            valid.append(it)
        elif it.source_kind == "xmind" and it.source_ref in allowed_node_ids:
            valid.append(it)
        # 其它情况丢弃

    return valid, 1, None


# ---------- 入口 ----------

def extract(
    batch: NormalizedBatch,
    *,
    cfg: LLMConfig,
    chat_fn: Optional[ChatFn] = None,
    controller=None,  # 新增：进度控制器
    incremental: bool = False,  # 新增：是否启用增量分析
) -> tuple[list[ExtractedSignal], int, list[str]]:
    """对全量批次做信号抽取。

    Parameters
    ----------
    incremental : bool
        True 时只分析未处理过或用例内容有变化的项

    Returns
    -------
    (all_signals, llm_calls, errors)
    """
    import time
    from backend.core.legacy.analysis_cache import (
        load_cache,
        save_cache,
        is_case_analyzed,
        is_xmind_node_analyzed,
        mark_case_analyzed,
        mark_xmind_node_analyzed,
        get_cache_stats,
    )
    from backend.core.timeutil import utc_iso_z
    
    chat_fn = chat_fn or _default_chat
    all_signals: list[ExtractedSignal] = []
    errors: list[str] = []
    llm_calls = 0
    
    start_time = time.time()
    
    # 加载缓存（如果启用增量分析）
    cache = load_cache(batch.project) if incremental else None
    if incremental and cache:
        stats = get_cache_stats(cache)
        logger.info(f"[Stage 2] 增量模式：已缓存 {stats['cached_cases']} 个用例, {stats['cached_xmind_nodes']} 个XMind节点")

    # 用例分批
    cases = batch.case_units
    total_case_batches = (len(cases) + CASE_BATCH_SIZE - 1) // CASE_BATCH_SIZE if cases else 0
    total_leaf_batches = (len(batch.xmind_leaves) + LEAF_BATCH_SIZE - 1) // LEAF_BATCH_SIZE if batch.xmind_leaves else 0
    total_batches = total_case_batches + total_leaf_batches
    
    if controller:
        controller.update_progress(
            total_batches=total_batches,
            completed_batches=0,
            message=f"开始处理 {len(cases)} 个用例和 {len(batch.xmind_leaves)} 个XMind节点"
        )
    
    logger.info(f"[Stage 2] 开始处理 {len(cases)} 个用例，分 {total_case_batches} 批")
    
    for i in range(0, len(cases), CASE_BATCH_SIZE):
        # 检查是否取消
        if controller and controller.is_cancelled():
            logger.info("[Stage 2] 分析已取消，停止处理用例")
            break
        
        # 如果暂停则等待
        if controller:
            controller.wait_if_paused()
            # 再次检查是否取消（从暂停恢复后）
            if controller.is_cancelled():
                break
        
        batch_num = i // CASE_BATCH_SIZE + 1
        chunk = cases[i : i + CASE_BATCH_SIZE]
        
        # 增量模式：过滤已分析的用例
        if incremental and cache:
            filtered_chunk = []
            skipped_count = 0
            for case in chunk:
                # 构建用例内容指纹
                content = f"{case.title}|{case.preconditions}|{str(case.step_pairs)}"
                if is_case_analyzed(cache, case.case_id, content):
                    skipped_count += 1
                else:
                    filtered_chunk.append(case)
            
            if skipped_count > 0:
                logger.info(f"[Stage 2] 批次 {batch_num} 跳过 {skipped_count} 个已分析用例")
            
            if not filtered_chunk:
                logger.info(f"[Stage 2] 批次 {batch_num} 全部跳过")
                if controller:
                    controller.update_progress(
                        completed_batches=batch_num,
                        llm_calls=llm_calls,
                        extracted_signals=len(all_signals),
                        message=f"已完成 {batch_num}/{total_case_batches} 用例批次"
                    )
                continue
            
            chunk = filtered_chunk
        batch_start = time.time()
        
        logger.info(f"[Stage 2] 处理用例批次 {batch_num}/{total_case_batches} ({len(chunk)} 个用例)...")
        
        if controller:
            controller.update_progress(
                current_batch=batch_num,
                batch_type="case",
                message=f"处理用例批次 {batch_num}/{total_case_batches}"
            )
        
        sigs, calls, err = _run_batch(chunk, [], cfg=cfg, chat_fn=chat_fn)
        
        elapsed = time.time() - batch_start
        all_signals.extend(sigs)
        llm_calls += calls
        
        # 增量模式：更新缓存
        if incremental and cache and not err:
            for case in chunk:
                content = f"{case.title}|{case.preconditions}|{str(case.step_pairs)}"
                mark_case_analyzed(cache, case.case_id, content, signals_count=len([s for s in sigs if s.source_ref == case.case_id]))
        
        if err:
            errors.append(f"[case batch {batch_num}] {err}")
            logger.warning(f"[Stage 2] 批次 {batch_num} 失败: {err}")
        else:
            logger.info(f"[Stage 2] 批次 {batch_num} 完成，耗时 {elapsed:.1f}s，提取 {len(sigs)} 个信号")
        
        if controller:
            controller.update_progress(
                completed_batches=batch_num,
                llm_calls=llm_calls,
                extracted_signals=len(all_signals),
                message=f"已完成 {batch_num}/{total_case_batches} 用例批次"
            )

    # XMind 叶子分批
    leaves = batch.xmind_leaves
    
    if leaves:
        logger.info(f"[Stage 2] 开始处理 {len(leaves)} 个XMind叶子节点，分 {total_leaf_batches} 批")
    
    for i in range(0, len(leaves), LEAF_BATCH_SIZE):
        # 检查是否取消
        if controller and controller.is_cancelled():
            logger.info("[Stage 2] 分析已取消，停止处理XMind")
            break
        
        # 如果暂停则等待
        if controller:
            controller.wait_if_paused()
            if controller.is_cancelled():
                break
        
        batch_num = i // LEAF_BATCH_SIZE + 1
        overall_batch_num = total_case_batches + batch_num  # 总体批次号
        chunk = leaves[i : i + LEAF_BATCH_SIZE]
        
        # 增量模式：过滤已分析的XMind节点
        if incremental and cache:
            filtered_chunk = []
            skipped_count = 0
            for leaf in chunk:
                # 构建节点内容指纹
                content = f"{leaf.title}|{'/'.join(leaf.path)}|{leaf.note or ''}"
                if is_xmind_node_analyzed(cache, leaf.node_id, content):
                    skipped_count += 1
                else:
                    filtered_chunk.append(leaf)
            
            if skipped_count > 0:
                logger.info(f"[Stage 2] XMind批次 {batch_num} 跳过 {skipped_count} 个已分析节点")
            
            if not filtered_chunk:
                logger.info(f"[Stage 2] XMind批次 {batch_num} 全部跳过")
                if controller:
                    controller.update_progress(
                        completed_batches=overall_batch_num,
                        llm_calls=llm_calls,
                        extracted_signals=len(all_signals),
                        message=f"已完成 {overall_batch_num}/{total_batches} 总批次"
                    )
                continue
            
            chunk = filtered_chunk
        batch_start = time.time()
        
        logger.info(f"[Stage 2] 处理XMind批次 {batch_num}/{total_leaf_batches} ({len(chunk)} 个节点)...")
        
        if controller:
            controller.update_progress(
                current_batch=overall_batch_num,
                batch_type="xmind",
                message=f"处理XMind批次 {batch_num}/{total_leaf_batches}"
            )
        
        sigs, calls, err = _run_batch([], chunk, cfg=cfg, chat_fn=chat_fn)
        
        elapsed = time.time() - batch_start
        all_signals.extend(sigs)
        llm_calls += calls
        
        # 增量模式：更新缓存
        if incremental and cache and not err:
            for leaf in chunk:
                content = f"{leaf.title}|{'/'.join(leaf.path)}|{leaf.note or ''}"
                mark_xmind_node_analyzed(cache, leaf.node_id, content, signals_count=len([s for s in sigs if s.source_ref == leaf.node_id]))
        
        if err:
            errors.append(f"[xmind batch {batch_num}] {err}")
            logger.warning(f"[Stage 2] XMind批次 {batch_num} 失败: {err}")
        else:
            logger.info(f"[Stage 2] XMind批次 {batch_num} 完成，耗时 {elapsed:.1f}s，提取 {len(sigs)} 个信号")
        
        if controller:
            controller.update_progress(
                completed_batches=overall_batch_num,
                llm_calls=llm_calls,
                extracted_signals=len(all_signals),
                message=f"已完成 {overall_batch_num}/{total_batches} 总批次"
            )

    total_elapsed = time.time() - start_time
    logger.info(f"[Stage 2] 全部完成！总耗时 {total_elapsed:.1f}s，LLM调用 {llm_calls} 次，提取 {len(all_signals)} 个信号")
    
    # 保存缓存（如果启用增量分析）
    if incremental and cache:
        from backend.core.timeutil import utc_iso_z
        cache.last_full_analysis = utc_iso_z()
        save_cache(batch.project, cache)
        stats = get_cache_stats(cache)
        logger.info(f"[Stage 2] 缓存已更新：{stats['cached_cases']} 个用例, {stats['cached_xmind_nodes']} 个XMind节点")

    return all_signals, llm_calls, errors
