"""PR6.1：conflict_store 单元测试。"""
from __future__ import annotations

import json

import pytest

from backend.core import conflict_store
from backend.schemas.conflict import ConflictPair


PROJECT = "demo"


def _cf(cid: str, a: str = "KP_A_001", b: str = "KP_B_001") -> ConflictPair:
    return ConflictPair(
        conflict_id=cid,
        kp_ids=[a, b],
        type="numeric",
        severity="medium",
        module="登录",
        description="最大重试次数 5 vs 10",
        detected_at="2026-04-29T00:00:00Z",
    )


# ---- sequence / id -----------------------------------------------------------

def test_next_conflict_id_monotonic(tmp_settings):
    a = conflict_store.next_conflict_id(PROJECT)
    b = conflict_store.next_conflict_id(PROJECT)
    assert a == "cf_demo_0001"
    assert b == "cf_demo_0002"


def test_next_conflict_id_slug_fallback(tmp_settings):
    # 全中文项目名：默认策略去非 alnum 后为空，落到 "x" slug
    cid = conflict_store.next_conflict_id("测试项目")
    assert cid == "cf_x_0001"


# ---- load / save -----------------------------------------------------------

def test_load_empty_returns_list(tmp_settings):
    assert conflict_store.load_all(PROJECT) == []


def test_save_and_load_roundtrip(tmp_settings):
    c1 = _cf("cf_demo_0001")
    c2 = _cf("cf_demo_0002", a="KP_X", b="KP_Y")
    conflict_store.save_all(PROJECT, [c1, c2])
    loaded = conflict_store.load_all(PROJECT)
    assert [c.conflict_id for c in loaded] == ["cf_demo_0001", "cf_demo_0002"]


def test_save_is_atomic(tmp_settings):
    """tmp 文件在成功 rename 后应消失。"""
    conflict_store.save_all(PROJECT, [_cf("cf_demo_0001")])
    d = conflict_store._path(PROJECT).parent
    assert not list(d.glob("conflicts.json.tmp"))


def test_load_skips_broken_records(tmp_settings):
    """数据文件里混入坏记录时逐条尝试，不应整块丢失。"""
    p = conflict_store._path(PROJECT)
    p.parent.mkdir(parents=True, exist_ok=True)
    good = _cf("cf_demo_0001").model_dump()
    bad = {"conflict_id": "broken"}  # 缺必需字段
    p.write_text(json.dumps([good, bad], ensure_ascii=False), encoding="utf-8")
    loaded = conflict_store.load_all(PROJECT)
    assert len(loaded) == 1
    assert loaded[0].conflict_id == "cf_demo_0001"


# ---- upsert / delete -------------------------------------------------------

def test_upsert_replaces_by_id(tmp_settings):
    conflict_store.save_all(PROJECT, [_cf("cf_demo_0001")])
    updated = _cf("cf_demo_0001").model_copy(
        update={"resolution": "accept_first", "resolution_note": "以首条为准"},
    )
    conflict_store.upsert_one(PROJECT, updated)
    all_c = conflict_store.load_all(PROJECT)
    assert len(all_c) == 1
    assert all_c[0].resolution == "accept_first"


def test_upsert_appends_when_missing(tmp_settings):
    conflict_store.save_all(PROJECT, [_cf("cf_demo_0001")])
    conflict_store.upsert_one(PROJECT, _cf("cf_demo_0002"))
    assert len(conflict_store.load_all(PROJECT)) == 2


def test_delete_removes(tmp_settings):
    conflict_store.save_all(PROJECT, [_cf("cf_demo_0001"), _cf("cf_demo_0002")])
    assert conflict_store.delete_one(PROJECT, "cf_demo_0001") is True
    left = conflict_store.load_all(PROJECT)
    assert [c.conflict_id for c in left] == ["cf_demo_0002"]


def test_delete_missing_returns_false(tmp_settings):
    assert conflict_store.delete_one(PROJECT, "cf_demo_0001") is False


def test_clear_all_does_not_reset_seq(tmp_settings):
    conflict_store.next_conflict_id(PROJECT)
    conflict_store.next_conflict_id(PROJECT)
    conflict_store.save_all(PROJECT, [_cf("cf_demo_0002")])
    conflict_store.clear_all(PROJECT)
    assert conflict_store.load_all(PROJECT) == []
    # 序号继续递增而不是回到 0001
    assert conflict_store.next_conflict_id(PROJECT) == "cf_demo_0003"


# ---- pair helpers ----------------------------------------------------------

def test_pair_key_is_orderless(tmp_settings):
    assert conflict_store.pair_key("KP_B", "KP_A") == ("KP_A", "KP_B")
    assert conflict_store.pair_key("KP_A", "KP_B") == ("KP_A", "KP_B")


def test_existing_pair_keys(tmp_settings):
    conflict_store.save_all(PROJECT, [
        _cf("cf_demo_0001", "KP_1", "KP_2"),
        _cf("cf_demo_0002", "KP_3", "KP_4"),
    ])
    keys = conflict_store.existing_pair_keys(PROJECT)
    assert ("KP_1", "KP_2") in keys
    assert ("KP_3", "KP_4") in keys
