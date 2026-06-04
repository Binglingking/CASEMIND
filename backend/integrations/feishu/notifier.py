"""F3 - 解析/分析完成 Bot 通知。

钩子点：
  - legacy_service.ingest_excel 在新解析完成（非幂等命中）时调 notify_legacy_ingest_done
  - case_gen_service.run_step 在 step4 完成（state.current_step == 'completed'）时调 notify_case_gen_done

设计要点：
  - 任何失败都被吞掉并记日志，**绝不影响主流程**（飞书是旁路通知，不是关键路径）
  - 守卫顺序：feature flag → 项目级 enabled → 子开关 f3_done_notify → owners/chat_id 至少有一个
  - 同时支持给 default_chat_id 推群消息 + 给每个 owner 单推
"""
from __future__ import annotations

import logging
from typing import Any

from backend.integrations.feishu import cards
from backend.integrations.feishu.client import FeishuClient, get_client
from backend.integrations.feishu.config import load_config

logger = logging.getLogger(__name__)


def _features_enabled() -> bool:
    # 延迟导入避免在测试单跑 feishu 模块时拖入 settings/routes 链路
    try:
        from backend.api.routes_settings import get_runtime_features
        return bool(get_runtime_features().enable_feishu_integration)
    except Exception as e:
        logger.debug("[feishu.notifier] feature check failed: %s", e)
        return False


def _targets(cfg) -> list[str]:
    out: list[str] = []
    if cfg.default_chat_id:
        out.append(cfg.default_chat_id)
    for o in cfg.owners or []:
        if o.open_id:
            out.append(o.open_id)
    return out


def _send(card: dict[str, Any], project: str, client: FeishuClient | None) -> int:
    """发送给该项目的所有 target（chat + owners）。返回成功推送数。"""
    cfg = load_config(project)
    targets = _targets(cfg)
    if not targets:
        logger.info("[feishu.notifier] no targets configured for %s, skip", project)
        return 0
    cli = client or get_client(project)
    sent = 0
    for t in targets:
        try:
            cli.send_card(t, card)
            sent += 1
        except Exception as e:
            logger.warning("[feishu.notifier] send to %s failed: %s", t, e)
    return sent


def _should_notify(project: str, subfeature: str = "f3_done_notify") -> bool:
    if not _features_enabled():
        return False
    cfg = load_config(project)
    if not cfg.enabled:
        return False
    if not getattr(cfg.subfeatures, subfeature, False):
        return False
    return True


def notify_legacy_ingest_done(
    *,
    project: str,
    filename: str,
    case_count: int,
    warnings_count: int,
    detail_url: str = "",
    client: FeishuClient | None = None,
) -> int:
    """legacy_service.ingest_excel 完成后调用。

    返回成功推送数；任何异常被吞掉返回 0。
    """
    try:
        if not _should_notify(project):
            return 0
        card = cards.render_done_notify(
            project=project,
            filename=filename,
            case_count=case_count,
            warnings_count=warnings_count,
            detail_url=detail_url or f"/projects/{project}/legacy",
        )
        return _send(card, project, client)
    except Exception as e:
        logger.warning("[feishu.notifier] notify_legacy_ingest_done failed: %s", e)
        return 0


def notify_case_gen_done(
    *,
    project: str,
    pipeline_id: str,
    case_count: int,
    warnings_count: int = 0,
    detail_url: str = "",
    client: FeishuClient | None = None,
) -> int:
    """case_gen pipeline step4 完成后调用。"""
    try:
        if not _should_notify(project):
            return 0
        card = cards.render_done_notify(
            project=project,
            filename=f"用例生成 {pipeline_id}",
            case_count=case_count,
            warnings_count=warnings_count,
            detail_url=detail_url or f"/projects/{project}/case-gen/{pipeline_id}",
        )
        return _send(card, project, client)
    except Exception as e:
        logger.warning("[feishu.notifier] notify_case_gen_done failed: %s", e)
        return 0
