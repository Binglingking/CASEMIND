"""PR7.1：feedback_store 单元测试。"""
from __future__ import annotations

import json

import pytest

from backend.core import feedback_store
from backend.schemas.feedback import FeedbackRecord


PROJECT = "demo"


def _fb(fid: str, *, target_id: str = "TC_登录_0001",
        kind: str = "up", created_at: str = "2026-04-29T10:00:00Z") -> FeedbackRecord:
    return FeedbackRecord(
        feedback_id=fid, target_type="case", target_id=target_id,
        pipeline_id="pl_20260429_100000_abcd",
        module="登录", kind=kind,
        note="ok" if kind == "up" else ("不够细" if kind == "down" else ""),
        snapshot={"case_id": target_id, "title": "登录成功"},
        created_at=created_at,
    )


# ---- id ---------------------------------------------------------------------

def test_next_feedback_id_monotonic(tmp_settings):
    a = feedback_store.next_feedback_id(PROJECT)
    b = feedback_store.next_feedback_id(PROJECT)
    assert a == "fb_demo_000001"
    assert b == "fb_demo_000002"


def test_next_feedback_id_slug_fallback(tmp_settings):
    cid = feedback_store.next_feedback_id("测试项目")
    assert cid == "fb_x_000001"


# ---- load / save -----------------------------------------------------------

def test_load_empty(tmp_settings):
    assert feedback_store.load_all(PROJECT) == []


def test_save_and_load_roundtrip(tmp_settings):
    r1 = _fb("fb_demo_000001")
    r2 = _fb("fb_demo_000002", kind="down")
    feedback_store.save_all(PROJECT, [r1, r2])
    loaded = feedback_store.load_all(PROJECT)
    assert [r.feedback_id for r in loaded] == ["fb_demo_000001", "fb_demo_000002"]
    assert loaded[1].kind == "down"


def test_save_is_atomic(tmp_settings):
    feedback_store.save_all(PROJECT, [_fb("fb_demo_000001")])
    d = feedback_store._path(PROJECT).parent
    assert not list(d.glob("feedback.json.tmp"))


def test_load_skips_broken_records(tmp_settings):
    p = feedback_store._path(PROJECT)
    p.parent.mkdir(parents=True, exist_ok=True)
    good = _fb("fb_demo_000001").model_dump()
    bad = {"feedback_id": "broken"}
    p.write_text(json.dumps([good, bad], ensure_ascii=False), encoding="utf-8")
    loaded = feedback_store.load_all(PROJECT)
    assert len(loaded) == 1
    assert loaded[0].feedback_id == "fb_demo_000001"


# ---- append / delete -------------------------------------------------------

def test_append_one(tmp_settings):
    feedback_store.append_one(PROJECT, _fb("fb_demo_000001"))
    feedback_store.append_one(PROJECT, _fb("fb_demo_000002", kind="down"))
    assert len(feedback_store.load_all(PROJECT)) == 2


def test_delete_one(tmp_settings):
    feedback_store.save_all(PROJECT, [_fb("fb_demo_000001"), _fb("fb_demo_000002")])
    assert feedback_store.delete_one(PROJECT, "fb_demo_000001") is True
    left = feedback_store.load_all(PROJECT)
    assert [r.feedback_id for r in left] == ["fb_demo_000002"]


def test_delete_missing_returns_false(tmp_settings):
    assert feedback_store.delete_one(PROJECT, "fb_demo_000001") is False


def test_clear_does_not_reset_seq(tmp_settings):
    feedback_store.next_feedback_id(PROJECT)
    feedback_store.next_feedback_id(PROJECT)
    feedback_store.save_all(PROJECT, [_fb("fb_demo_000002")])
    feedback_store.clear_all(PROJECT)
    assert feedback_store.load_all(PROJECT) == []
    assert feedback_store.next_feedback_id(PROJECT) == "fb_demo_000003"


# ---- 查询辅助 --------------------------------------------------------------

def test_find_by_target(tmp_settings):
    feedback_store.save_all(PROJECT, [
        _fb("fb_demo_000001", target_id="TC_A"),
        _fb("fb_demo_000002", target_id="TC_B"),
        _fb("fb_demo_000003", target_id="TC_A", kind="down"),
    ])
    hits = feedback_store.find_by_target(PROJECT, "TC_A")
    assert [h.feedback_id for h in hits] == ["fb_demo_000001", "fb_demo_000003"]


def test_find_latest_per_target(tmp_settings):
    feedback_store.save_all(PROJECT, [
        _fb("fb_demo_000001", target_id="TC_A",
            kind="up",   created_at="2026-04-29T10:00:00Z"),
        _fb("fb_demo_000002", target_id="TC_A",
            kind="down", created_at="2026-04-29T11:00:00Z"),
        _fb("fb_demo_000003", target_id="TC_B",
            kind="up",   created_at="2026-04-29T10:30:00Z"),
    ])
    latest = feedback_store.find_latest_per_target(PROJECT)
    assert latest["TC_A"].feedback_id == "fb_demo_000002"  # 后写入的那条
    assert latest["TC_B"].feedback_id == "fb_demo_000003"
