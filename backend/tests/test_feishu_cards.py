"""飞书卡片模板结构校验。"""
from __future__ import annotations

from backend.integrations.feishu import cards


def _has_action_button(card: dict, label: str) -> bool:
    for el in card.get("elements", []):
        if el.get("tag") == "action":
            for act in el.get("actions", []):
                if act.get("text", {}).get("content") == label:
                    return True
    return False


def test_done_notify_shape():
    card = cards.render_done_notify(
        project="proj_a", filename="x.xlsx",
        case_count=10, warnings_count=2,
        detail_url="https://platform/detail",
    )
    assert card["header"]["title"]["content"].startswith("CaseMind")
    assert _has_action_button(card, "查看详情")


def test_error_alert_at_mentions_owners():
    card = cards.render_error_alert(
        project="proj_a", filename="x.xlsx",
        error_count=3, sample_errors=["e1", "e2"],
        owners=["ou_aaa", "ou_bbb"],
        detail_url="https://platform/err",
    )
    md = card["elements"][0]["text"]["content"]
    assert '<at id="ou_aaa"></at>' in md
    assert '<at id="ou_bbb"></at>' in md
    assert "e1" in md and "e2" in md


def test_review_kp_carries_callback_value():
    card = cards.render_review_kp(
        project="p", kp_id="kp_x", kp_title="t", kp_summary="s",
        confidence=0.85,
        callback_value_base={"src": "f6"},
    )
    actions = card["elements"][1]["actions"]
    accept = next(a for a in actions if a["text"]["content"] == "通过")
    reject = next(a for a in actions if a["text"]["content"] == "拒绝")
    assert accept["value"] == {"src": "f6", "kp_id": "kp_x", "action": "accept"}
    assert reject["value"] == {"src": "f6", "kp_id": "kp_x", "action": "reject"}


def test_im_mode_select_has_three_modes():
    card = cards.render_im_mode_select("p")
    modes = {a["value"]["mode"] for a in card["elements"][1]["actions"]}
    assert modes == {"qa", "case_gen", "review"}
