"""legacy_store 读写测试。"""
from __future__ import annotations

import pytest

from backend.core.legacy import legacy_store as store
from backend.core.timeutil import utc_iso_z
from backend.schemas.column_mapping import ColumnMapping, ProjectColumnMappingStore
from backend.schemas.inferred_kp import (
    InferredKnowledgePoint,
    InferredSource,
)
from backend.schemas.legacy_case import LegacyCase, LegacyCaseFile, LegacyCaseStep
from backend.schemas.legacy_xmind import LegacyXMindNode, LegacyXMindTree
from backend.schemas.style_profile import StyleProfile


PROJECT = "demo"


def _meta(file_id: str = "abc12345") -> LegacyCaseFile:
    return LegacyCaseFile(
        file_id=file_id, name="cases.xlsx", ext=".xlsx",
        size=100, mtime=1.0, uploaded_at=utc_iso_z(),
        case_count=1, sheet_names=["Sheet1"],
    )


def _case(file_id: str = "abc12345") -> LegacyCase:
    return LegacyCase(
        case_id=f"LC_{file_id}_0002",
        suite="支付", module="下单", sub_item="金额-正常流程",
        sub_item_base="金额", stage="正常流程",
        title="正确金额-下单成功", preconditions="已登录",
        steps=[LegacyCaseStep(index=1, action="提交", expected="成功")],
        case_type="功能测试", priority="P0", creator="alice",
        source_file="cases.xlsx", source_row=2,
    )


def test_upsert_and_load_case_file(tmp_settings):
    meta = _meta()
    case = _case()
    store.upsert_case_file(PROJECT, meta, [case])

    files = store.list_case_files(PROJECT)
    assert len(files) == 1
    assert files[0].file_id == "abc12345"

    loaded = store.load_cases(PROJECT, "abc12345")
    assert len(loaded) == 1
    assert loaded[0].title == "正确金额-下单成功"


def test_upsert_case_file_replaces_same_id(tmp_settings):
    store.upsert_case_file(PROJECT, _meta(), [_case()])
    new_meta = _meta()
    new_meta.case_count = 2
    store.upsert_case_file(PROJECT, new_meta, [_case(), _case()])
    files = store.list_case_files(PROJECT)
    assert len(files) == 1
    assert files[0].case_count == 2
    assert len(store.load_cases(PROJECT, "abc12345")) == 2


def test_delete_case_file(tmp_settings):
    store.upsert_case_file(PROJECT, _meta(), [_case()])
    store.delete_case_file(PROJECT, "abc12345")
    assert store.list_case_files(PROJECT) == []
    assert store.load_cases(PROJECT, "abc12345") == []


def test_all_cases_aggregates(tmp_settings):
    store.upsert_case_file(PROJECT, _meta("aaaaaaaa"), [_case("aaaaaaaa")])
    store.upsert_case_file(PROJECT, _meta("bbbbbbbb"), [_case("bbbbbbbb"), _case("bbbbbbbb")])
    assert len(store.all_cases(PROJECT)) == 3


def test_xmind_upsert_load_delete(tmp_settings):
    tree = LegacyXMindTree(
        file_id="xm123456",
        name="t.xmind", ext=".xmind",
        size=10, mtime=1.0, uploaded_at=utc_iso_z(),
        root_id="root",
        nodes=[LegacyXMindNode(
            node_id="root", title="R", depth=0, path=["R"], is_leaf=True,
        )],
    )
    store.upsert_xmind_tree(PROJECT, tree)
    files = store.list_xmind_files(PROJECT)
    assert files and files[0]["file_id"] == "xm123456"

    loaded = store.load_xmind_tree(PROJECT, "xm123456")
    assert loaded is not None
    assert loaded.name == "t.xmind"
    assert loaded.nodes[0].title == "R"

    store.delete_xmind_file(PROJECT, "xm123456")
    assert store.list_xmind_files(PROJECT) == []
    assert store.load_xmind_tree(PROJECT, "xm123456") is None


def test_column_mapping_roundtrip(tmp_settings):
    s = ProjectColumnMappingStore()
    s.by_fingerprint["fp1"] = ColumnMapping(
        header_to_standard={"用例名称": "用例名称"},
        confirmed=True, hit_ratio=1.0,
    )
    store.save_column_mapping_store(PROJECT, s)
    s2 = store.load_column_mapping_store(PROJECT)
    assert "fp1" in s2.by_fingerprint
    assert s2.by_fingerprint["fp1"].confirmed is True


def test_style_profile_roundtrip(tmp_settings):
    p = StyleProfile(project=PROJECT, generated_at=utc_iso_z())
    p.case_style.total_cases = 42
    store.save_style_profile(PROJECT, p)
    p2 = store.load_style_profile(PROJECT)
    assert p2 is not None
    assert p2.case_style.total_cases == 42


def test_inferred_kps_upsert(tmp_settings):
    item = InferredKnowledgePoint(
        inferred_id="IKP_aabbccdd",
        type="business_rule",
        content="支付金额必须 > 0",
        module="支付",
        source=InferredSource(
            kind="case", file="cases.xlsx", file_id="abc12345",
            case_id="LC_abc12345_0002", case_row=2,
        ),
        extracted_at=utc_iso_z(),
    )
    store.upsert_inferred_kps(PROJECT, [item])
    items = store.load_inferred_kps(PROJECT)
    assert len(items) == 1
    assert items[0].review_status == "pending"

    # 同 ID 覆盖
    item2 = item.model_copy(update={"content": "支付金额必须 > 0 且 < 100000"})
    store.upsert_inferred_kps(PROJECT, [item2])
    items = store.load_inferred_kps(PROJECT)
    assert len(items) == 1
    assert items[0].content.endswith("< 100000")


def test_save_raw_copies_file(tmp_settings, tmp_path):
    src = tmp_path / "src.xlsx"
    src.write_bytes(b"fake-xlsx-bytes")
    target = store.save_raw(PROJECT, "fid12345", src)
    assert target.exists()
    assert target.read_bytes() == b"fake-xlsx-bytes"
    found = store.get_raw_path(PROJECT, "fid12345", ".xlsx")
    assert found is not None and found.exists()
