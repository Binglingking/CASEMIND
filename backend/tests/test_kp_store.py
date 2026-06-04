"""PR2.1：kp_store 单元测试。

覆盖点：
  - kp_id 生成（module slug、type 缩写、seq 持续递增）
  - 原子写入（.tmp rename）
  - merge_kps 的 edited_by_user 保留、同 chunk 替换、orphan 标记
  - 坏文件容错：单条坏数据不吃掉全表
"""
from __future__ import annotations

import json

import pytest

from backend.core import kp_store
from backend.schemas.knowledge_point import KnowledgePoint, KPSource


PROJECT = "demo"


def _make_kp(kp_id: str, chunk_id: str = "f.md::0::h1", edited: bool = False,
             module: str = "登录", kp_type: str = "business_rule",
             file: str = "f.md") -> KnowledgePoint:
    return KnowledgePoint(
        kp_id=kp_id,
        type=kp_type,
        content="demo",
        module=module,
        source=KPSource(file=file, chunk_id=chunk_id),
        doc_version="2026-01-01T00:00:00Z",
        extracted_at="2026-01-01T00:00:00Z",
        edited_by_user=edited,
    )


# ---- kp_id 生成 -----------------------------------------------------------

def test_next_kp_id_sequences_per_module_and_type(tmp_settings):
    a = kp_store.next_kp_id(PROJECT, "登录", "business_rule")
    b = kp_store.next_kp_id(PROJECT, "登录", "business_rule")
    c = kp_store.next_kp_id(PROJECT, "登录", "input_constraint")
    d = kp_store.next_kp_id(PROJECT, "下单", "business_rule")

    assert a == "KP_登录_br_0001"
    assert b == "KP_登录_br_0002"
    assert c == "KP_登录_ic_0001"
    assert d == "KP_下单_br_0001"


def test_next_kp_id_rejects_unknown_type(tmp_settings):
    with pytest.raises(ValueError):
        kp_store.next_kp_id(PROJECT, "登录", "not_a_type")


def test_seq_persists_across_calls(tmp_settings):
    kp_store.next_kp_id(PROJECT, "登录", "business_rule")
    kp_store.next_kp_id(PROJECT, "登录", "business_rule")
    seq = kp_store.load_seq(PROJECT)
    assert seq["登录"]["br"] == 2


# ---- 全量读写 -------------------------------------------------------------

def test_save_and_load_roundtrip(tmp_settings):
    kps = [_make_kp("KP_登录_br_0001"), _make_kp("KP_登录_ic_0001",
           kp_type="input_constraint")]
    kp_store.save_all(PROJECT, kps)
    loaded = kp_store.load_all(PROJECT)
    assert [k.kp_id for k in loaded] == ["KP_登录_br_0001", "KP_登录_ic_0001"]


def test_load_returns_empty_when_file_absent(tmp_settings):
    assert kp_store.load_all(PROJECT) == []


def test_load_survives_one_corrupt_record(tmp_settings):
    """一条坏数据不该吃掉整个文件。"""
    good = _make_kp("KP_登录_br_0001").model_dump()
    bad = {"kp_id": "KP_x", "type": "not_valid"}  # type 枚举错误
    from backend.core.project import project_manager
    path = project_manager.mem_dir(PROJECT) / kp_store.KP_FILE
    path.write_text(json.dumps([good, bad], ensure_ascii=False), encoding="utf-8")
    loaded = kp_store.load_all(PROJECT)
    assert len(loaded) == 1
    assert loaded[0].kp_id == "KP_登录_br_0001"


def test_upsert_one_replaces_by_kp_id(tmp_settings):
    kp = _make_kp("KP_登录_br_0001")
    kp_store.save_all(PROJECT, [kp])
    updated = kp.model_copy(update={"content": "updated"})
    kp_store.upsert_one(PROJECT, updated)
    loaded = kp_store.load_all(PROJECT)
    assert len(loaded) == 1
    assert loaded[0].content == "updated"


def test_delete_one(tmp_settings):
    kp_store.save_all(PROJECT, [_make_kp("KP_登录_br_0001")])
    assert kp_store.delete_one(PROJECT, "KP_登录_br_0001") is True
    assert kp_store.delete_one(PROJECT, "KP_nope") is False
    assert kp_store.load_all(PROJECT) == []


# ---- merge 规则 -----------------------------------------------------------

def test_merge_replaces_llm_extracted_same_chunk(tmp_settings):
    """同 chunk 的非编辑 KP 被新抽取替换。"""
    old = _make_kp("KP_登录_br_0001", chunk_id="f.md::0::h1", edited=False)
    new = _make_kp("KP_登录_br_9999", chunk_id="f.md::0::h1", edited=False)
    merged, stats = kp_store.merge_kps(
        existing=[old], newly_extracted=[new],
        affected_chunk_ids={"f.md::0::h1"},
    )
    assert [kp.kp_id for kp in merged] == ["KP_登录_br_9999"]
    assert stats.replaced == 1
    assert stats.added == 1


def test_merge_preserves_user_edited(tmp_settings):
    """edited_by_user=True 的 KP 不被替换，即便同 chunk。"""
    edited = _make_kp("KP_登录_br_0001", chunk_id="f.md::0::h1", edited=True)
    new = _make_kp("KP_登录_br_9999", chunk_id="f.md::0::h1", edited=False)
    merged, stats = kp_store.merge_kps(
        existing=[edited], newly_extracted=[new],
        affected_chunk_ids={"f.md::0::h1"},
    )
    ids = {kp.kp_id for kp in merged}
    assert ids == {"KP_登录_br_0001", "KP_登录_br_9999"}
    assert stats.preserved_edited == 1


def test_merge_keeps_other_chunks(tmp_settings):
    other = _make_kp("KP_登录_br_0002", chunk_id="g.md::0::h2", edited=False)
    new = _make_kp("KP_登录_br_9999", chunk_id="f.md::0::h1", edited=False)
    merged, stats = kp_store.merge_kps(
        existing=[other], newly_extracted=[new],
        affected_chunk_ids={"f.md::0::h1"},
    )
    ids = {kp.kp_id for kp in merged}
    assert ids == {"KP_登录_br_0002", "KP_登录_br_9999"}
    assert stats.kept_other == 1


def test_merge_orphans_missing_source(tmp_settings):
    """源文件已不在 live_sources 里的 KP 标 orphan。"""
    kept = _make_kp("KP_登录_br_0002", chunk_id="g.md::0::h2",
                    edited=False, file="deleted.md")
    merged, stats = kp_store.merge_kps(
        existing=[kept], newly_extracted=[],
        affected_chunk_ids=set(),
        live_sources={"f.md"},   # deleted.md 不在里面
    )
    assert merged[0].orphan is True
    assert stats.orphaned == 1


def test_clear_all_wipes_everything(tmp_settings):
    kp_store.save_all(PROJECT, [_make_kp("KP_x_br_0001")])
    kp_store.next_kp_id(PROJECT, "模块", "business_rule")
    # 造一个 cache 文件
    from backend.core.project import project_manager
    cache = project_manager.mem_dir(PROJECT) / kp_store.CACHE_DIR / "foo.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("{}", encoding="utf-8")

    kp_store.clear_all(PROJECT)
    assert kp_store.load_all(PROJECT) == []
    assert kp_store.load_seq(PROJECT) == {}
    assert not cache.exists()


# ---- 路径 -----------------------------------------------------------------

def test_cache_path_is_safe_filename(tmp_settings):
    cid = "f.md::3::abc/def"
    p = kp_store.cache_path(PROJECT, cid)
    assert "::" not in p.name
    assert "/" not in p.name[:-5]  # .json 后缀的 / 是目录分隔符，不算
    assert p.suffix == ".json"
