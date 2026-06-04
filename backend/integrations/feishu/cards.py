"""飞书消息卡片模板（card v2 schema）。

每个 render_* 函数返回可直接喂 client.send_card 的 dict。
卡片内容尽量精简，详情链接回平台。
"""
from __future__ import annotations

from typing import Any


def _header(title: str, template: str = "blue") -> dict[str, Any]:
    return {
        "title": {"tag": "plain_text", "content": title},
        "template": template,
    }


def _at_users(open_ids: list[str]) -> str:
    return " ".join(f'<at id="{oid}"></at>' for oid in open_ids if oid)


def render_done_notify(
    *,
    project: str,
    filename: str,
    case_count: int,
    warnings_count: int,
    detail_url: str,
) -> dict[str, Any]:
    """F3 - 解析/分析完成通知。"""
    md = (
        f"**项目**：{project}\n"
        f"**文件**：{filename}\n"
        f"**用例数**：{case_count}\n"
        f"**告警数**：{warnings_count}"
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": _header("CaseMind · 解析完成", "green"),
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": md}},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "查看详情"},
                        "type": "primary",
                        "url": detail_url,
                    }
                ],
            },
        ],
    }


def render_error_alert(
    *,
    project: str,
    filename: str,
    error_count: int,
    sample_errors: list[str],
    owners: list[str],
    detail_url: str,
) -> dict[str, Any]:
    """F4 - error 级 warning 告警，@负责人。"""
    samples = "\n".join(f"- {e}" for e in sample_errors[:5]) or "（无样例）"
    at = _at_users(owners)
    md = (
        f"{at}\n"
        f"**项目**：{project}\n"
        f"**文件**：{filename}\n"
        f"**错误数**：{error_count}\n"
        f"**部分错误**：\n{samples}"
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": _header("CaseMind · 解析异常", "red"),
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": md}},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "查看异常详情"},
                        "type": "danger",
                        "url": detail_url,
                    }
                ],
            },
        ],
    }


def render_review_kp(
    *,
    project: str,
    kp_id: str,
    kp_title: str,
    kp_summary: str,
    confidence: float,
    callback_value_base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """F6 - 反哺候选审核卡片，两按钮调 card_callback。"""
    base = callback_value_base or {}
    md = (
        f"**项目**：{project}\n"
        f"**知识点ID**：`{kp_id}`\n"
        f"**标题**：{kp_title}\n"
        f"**摘要**：{kp_summary}\n"
        f"**置信度**：{confidence:.2f}"
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": _header("CaseMind · 反哺审核", "orange"),
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": md}},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "通过"},
                        "type": "primary",
                        "value": {**base, "kp_id": kp_id, "action": "accept"},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "拒绝"},
                        "type": "danger",
                        "value": {**base, "kp_id": kp_id, "action": "reject"},
                    },
                ],
            },
        ],
    }


def render_im_mode_select(project: str) -> dict[str, Any]:
    """F9 - IM 首次会话选模式。"""
    return {
        "config": {"wide_screen_mode": True},
        "header": _header(f"CaseMind · {project}", "blue"),
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "请选择对话模式：",
                },
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "知识问答"},
                        "type": "primary",
                        "value": {"mode": "qa"},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "用例生成"},
                        "value": {"mode": "case_gen"},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "反哺审核"},
                        "value": {"mode": "review"},
                    },
                ],
            },
        ],
    }
