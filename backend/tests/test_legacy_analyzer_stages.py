"""legacy_analyzer 各阶段单测。

Stage 2 用注入的 chat_fn mock，不发 HTTP。
"""
from __future__ import annotations

import json

from backend.agents.legacy_analyzer import (
    stage1_normalize,
    stage2_extract,
    stage3_style,
    stage4_aggregate,
    stage5_inferred,
    runner,
)
from backend.agents.legacy_analyzer.schemas import (
    ExtractedSignal,
    NormalizedBatch,
    NormalizedCaseUnit,
    NormalizedXMindLeaf,
)
from backend.core.legacy import legacy_store
from backend.core.llm import LLMConfig
from backend.core.timeutil import utc_iso_z
from backend.schemas.legacy_case import LegacyCase, LegacyCaseFile, LegacyCaseStep
from backend.schemas.legacy_xmind import LegacyXMindNode, LegacyXMindTree


PROJECT = "demo"


# ---------- 共享 fixture 工厂 ----------

def _seed_case(file_id: str = "f1234567", row: int = 2,
               title: str = "正确账密-登录成功", stage: str = "正常流程",
               steps_pairs: list[tuple[str, str]] | None = None) -> LegacyCase:
    pairs = steps_pairs or [
        ("打开登录页", "登录页可见"),
        ("输入账号密码", "输入框可输入"),
        ("点击登录", "跳转首页"),
    ]
    return LegacyCase(
        case_id=f"LC_{file_id}_{row:04d}",
        suite="登录", module="账号", sub_item="登录-正常流程",
        sub_item_base="登录", stage=stage,
        title=title, preconditions="已注册",
        steps=[LegacyCaseStep(index=i + 1, action=a, expected=e)
               for i, (a, e) in enumerate(pairs)],
        case_type="功能测试", priority="P0", creator="alice",
        source_file="cases.xlsx", source_row=row,
    )


def _seed_xmind(file_id: str = "x1234567") -> LegacyXMindTree:
    nodes = [
        LegacyXMindNode(node_id="n_root", title="支付", depth=0,
                        path=["支付"], parent_id=None,
                        children_ids=["n_a"], is_leaf=False),
        LegacyXMindNode(node_id="n_a", title="下单", depth=1,
                        path=["支付", "下单"], parent_id="n_root",
                        children_ids=["n_b"], is_leaf=False),
        LegacyXMindNode(node_id="n_b", title="金额校验", depth=2,
                        path=["支付", "下单", "金额校验"], parent_id="n_a",
                        children_ids=["n_c1", "n_c2"], is_leaf=False),
        LegacyXMindNode(node_id="n_c1", title="金额>0", depth=3,
                        path=["支付", "下单", "金额校验", "金额>0"],
                        parent_id="n_b", children_ids=[], is_leaf=True),
        LegacyXMindNode(node_id="n_c2", title="金额<=99999", depth=3,
                        path=["支付", "下单", "金额校验", "金额<=99999"],
                        parent_id="n_b", children_ids=[], is_leaf=True),
    ]
    return LegacyXMindTree(
        file_id=file_id, name="pay.xmind", ext=".xmind",
        size=10, mtime=1.0, uploaded_at=utc_iso_z(),
        root_id="n_root", nodes=nodes,
    )


def _seed_store(tmp_settings):
    case = _seed_case()
    legacy_store.upsert_case_file(
        PROJECT,
        LegacyCaseFile(
            file_id="f1234567", name="cases.xlsx", ext=".xlsx",
            size=100, mtime=1.0, uploaded_at=utc_iso_z(),
            case_count=1, sheet_names=["Sheet1"],
        ),
        [case],
    )
    legacy_store.upsert_xmind_tree(PROJECT, _seed_xmind())


# ---------- Stage 1 ----------

def test_stage1_normalize_reads_cases_and_leaves(tmp_settings):
    _seed_store(tmp_settings)
    batch = stage1_normalize.normalize(PROJECT)
    assert batch.project == PROJECT
    assert len(batch.case_units) == 1
    cu = batch.case_units[0]
    assert cu.case_id.startswith("LC_f1234567_")
    assert cu.module == "账号"
    assert len(cu.step_pairs) == 3
    assert cu.step_pairs[0] == ("打开登录页", "登录页可见")

    # 叶子 + 中间节点分流
    leaf_titles = {n.title for n in batch.xmind_leaves}
    mid_titles = {n.title for n in batch.xmind_mid_nodes}
    assert leaf_titles == {"金额>0", "金额<=99999"}
    assert "金额校验" in mid_titles    # depth=2 入中间层
    assert "下单" not in mid_titles     # depth=1 不入（< MID_DEPTH_MIN）


def test_stage1_normalize_empty_project(tmp_settings):
    batch = stage1_normalize.normalize("empty_project_xx")
    assert batch.case_units == []
    assert batch.xmind_leaves == []


# ---------- Stage 2 ----------

def _mk_batch_one_case_one_leaf() -> NormalizedBatch:
    return NormalizedBatch(
        project=PROJECT,
        case_units=[NormalizedCaseUnit(
            case_id="LC_aabb_0002", file_id="aabb",
            source_file="x.xlsx", source_row=2,
            suite="", module="账号", sub_item_base="登录", stage="正常流程",
            title="正确账密-登录成功", preconditions="已注册",
            step_pairs=[("点击登录", "跳转首页")],
            priority="P0", case_type="功能测试",
        )],
        xmind_leaves=[NormalizedXMindLeaf(
            node_id="n_x1", file_id="xx", source_file="t.xmind",
            title="金额>0", path=["支付", "下单", "金额", "金额>0"],
        )],
    )


def _make_chat_returning(items: list[dict]):
    payload = json.dumps({"items": items}, ensure_ascii=False)

    def chat(messages, cfg):
        return payload
    return chat


def test_stage2_extract_happy_path(tmp_settings):
    batch = _mk_batch_one_case_one_leaf()
    chat = _make_chat_returning([
        {
            "type": "business_rule",
            "content": "登录成功后自动跳转首页",
            "module": "账号",
            "aliases": [],
            "source_kind": "case",
            "source_ref": "LC_aabb_0002",
            "confidence": 0.85,
            "reasoning": "用例预期未在需求中显式声明",
        },
        {
            "type": "boundary",
            "content": "支付金额必须 > 0",
            "module": "支付",
            "aliases": [],
            "source_kind": "xmind",
            "source_ref": "n_x1",
            "confidence": 0.9,
            "reasoning": "叶子节点直接陈述",
        },
    ])
    sigs, calls, errors = stage2_extract.extract(
        batch, cfg=LLMConfig(), chat_fn=chat,
    )
    assert errors == []
    assert calls == 2  # 1 case batch + 1 leaf batch
    # 每批返回都包含两条信号，但只有匹配 source_ref 的会保留
    # case 批次：只 case 信号有效；leaf 批次：只 xmind 信号有效
    assert len(sigs) == 2
    types = {s.type for s in sigs}
    assert "business_rule" in types
    assert "boundary" in types


def test_stage2_extract_drops_invalid_source_ref(tmp_settings):
    batch = _mk_batch_one_case_one_leaf()
    chat = _make_chat_returning([
        {
            "type": "business_rule", "content": "x", "module": "账号",
            "source_kind": "case", "source_ref": "LC_NOT_EXIST",
            "confidence": 0.9, "reasoning": "",
        }
    ])
    sigs, _, errors = stage2_extract.extract(batch, cfg=LLMConfig(), chat_fn=chat)
    assert errors == []
    assert sigs == [], "未匹配 source_ref 的必须丢弃"


def test_stage2_extract_drops_low_confidence(tmp_settings):
    batch = _mk_batch_one_case_one_leaf()
    chat = _make_chat_returning([
        {
            "type": "business_rule", "content": "x", "module": "账号",
            "source_kind": "case", "source_ref": "LC_aabb_0002",
            "confidence": 0.3, "reasoning": "",
        }
    ])
    sigs, _, _ = stage2_extract.extract(batch, cfg=LLMConfig(), chat_fn=chat)
    assert sigs == [], "confidence < 0.5 的必须丢弃"


def test_stage2_extract_handles_chat_exception(tmp_settings):
    batch = _mk_batch_one_case_one_leaf()

    def boom(messages, cfg):
        raise RuntimeError("network down")
    sigs, calls, errors = stage2_extract.extract(batch, cfg=LLMConfig(), chat_fn=boom)
    assert sigs == []
    assert calls == 0
    assert any("LLM 调用失败" in e for e in errors)


# ---------- Stage 3 ----------

def test_stage3_style_basic_distributions(tmp_settings):
    _seed_store(tmp_settings)
    batch = stage1_normalize.normalize(PROJECT)
    stats = stage3_style.compute_style(PROJECT, batch)

    assert stats.total_cases == 1
    assert stats.title_scenario_expected_ratio == 1.0       # "正确账密-登录成功" 命中
    assert stats.avg_steps_per_case == 3.0
    assert stats.steps_expected_aligned_ratio == 1.0
    assert stats.stage_distribution.get("正常流程") == 1.0
    assert stats.priority_distribution.get("P0") == 1.0
    assert stats.total_trees == 1
    assert stats.max_depth == 3
    assert stats.total_nodes == 5


def test_stage3_style_title_not_scenario_format(tmp_settings):
    case = _seed_case(title="一个不带破折号的标题")
    legacy_store.upsert_case_file(
        PROJECT,
        LegacyCaseFile(
            file_id="f1234567", name="cases.xlsx", ext=".xlsx",
            size=100, mtime=1.0, uploaded_at=utc_iso_z(),
            case_count=1, sheet_names=["Sheet1"],
        ),
        [case],
    )
    batch = stage1_normalize.normalize(PROJECT)
    stats = stage3_style.compute_style(PROJECT, batch)
    assert stats.title_scenario_expected_ratio == 0.0


# ---------- Stage 4 ----------

def test_stage4_aggregate_dedup_same_content(tmp_settings):
    s1 = ExtractedSignal(
        type="business_rule", content="登录成功跳转首页", module="账号",
        source_kind="case", source_ref="LC_a_0002", confidence=0.7,
    )
    s2 = ExtractedSignal(
        type="business_rule", content="  登录成功 跳转首页 ", module="账号",
        source_kind="case", source_ref="LC_a_0003", confidence=0.9,
    )
    s3 = ExtractedSignal(
        type="boundary", content="金额>0", module="支付",
        source_kind="xmind", source_ref="n_1", confidence=0.95,
    )
    agg = stage4_aggregate.aggregate([s1, s2, s3])
    assert len(agg.items) == 2
    assert agg.duplicates_dropped == 1
    # 高置信度版本被保留
    kept = next(i for i in agg.items if i.module == "账号")
    assert kept.confidence == 0.9
    assert "账号" in agg.by_module
    assert "支付" in agg.by_module


# ---------- Stage 5 ----------

def test_stage5_inferred_keeps_case_source(tmp_settings):
    _seed_store(tmp_settings)
    batch = stage1_normalize.normalize(PROJECT)
    case_id = batch.case_units[0].case_id
    s = ExtractedSignal(
        type="business_rule", content="登录成功跳转首页", module="账号",
        source_kind="case", source_ref=case_id, confidence=0.85,
        reasoning="预期默认成立",
    )
    from backend.agents.legacy_analyzer.schemas import AggregatedSignals
    agg = AggregatedSignals(items=[s], by_module={"账号": [s.content]})
    items = stage5_inferred.to_inferred_kps(agg, batch)
    assert len(items) == 1
    it = items[0]
    assert it.review_status == "pending_review"
    assert it.source.kind == "case"
    assert it.source.case_id == case_id
    assert it.source.case_row == 2
    assert it.inferred_id.startswith("IKP_")


def test_stage5_inferred_keeps_xmind_source(tmp_settings):
    _seed_store(tmp_settings)
    batch = stage1_normalize.normalize(PROJECT)
    leaf_id = next(n.node_id for n in batch.xmind_leaves if n.title == "金额>0")
    s = ExtractedSignal(
        type="boundary", content="支付金额必须 > 0", module="支付",
        source_kind="xmind", source_ref=leaf_id, confidence=0.9,
    )
    from backend.agents.legacy_analyzer.schemas import AggregatedSignals
    agg = AggregatedSignals(items=[s], by_module={"支付": [s.content]})
    items = stage5_inferred.to_inferred_kps(agg, batch)
    assert len(items) == 1
    assert items[0].source.kind == "xmind"
    assert items[0].source.node_path[-1] == "金额>0"


def test_stage5_inferred_drops_orphan_source(tmp_settings):
    _seed_store(tmp_settings)
    batch = stage1_normalize.normalize(PROJECT)
    s = ExtractedSignal(
        type="business_rule", content="x", module="账号",
        source_kind="case", source_ref="LC_no_such_id", confidence=0.9,
    )
    from backend.agents.legacy_analyzer.schemas import AggregatedSignals
    agg = AggregatedSignals(items=[s])
    assert stage5_inferred.to_inferred_kps(agg, batch) == []


def test_stage5_persist_writes_pending(tmp_settings):
    _seed_store(tmp_settings)
    batch = stage1_normalize.normalize(PROJECT)
    case_id = batch.case_units[0].case_id
    s = ExtractedSignal(
        type="business_rule", content="登录成功跳转首页", module="账号",
        source_kind="case", source_ref=case_id, confidence=0.85,
    )
    from backend.agents.legacy_analyzer.schemas import AggregatedSignals
    items = stage5_inferred.to_inferred_kps(
        AggregatedSignals(items=[s]), batch
    )
    stage5_inferred.persist(PROJECT, items)
    on_disk = legacy_store.load_inferred_kps(PROJECT)
    assert len(on_disk) == 1
    assert on_disk[0].review_status == "pending_review"


# ---------- Runner ----------

def test_runner_run_skip_extract_writes_style_profile(tmp_settings):
    _seed_store(tmp_settings)
    res = runner.run(PROJECT, cfg=LLMConfig(), skip_extract=True)
    assert res.case_units_count == 1
    assert res.xmind_leaves_count == 2
    assert res.llm_calls == 0
    assert res.extracted_count == 0
    profile = legacy_store.load_style_profile(PROJECT)
    assert profile is not None
    assert profile.case_style.total_cases == 1
    assert profile.xmind_style.max_depth == 3


def test_runner_run_with_chat_fn_persists_inferred(tmp_settings, monkeypatch):
    from backend.config import Features
    from backend.api import routes_settings as _rs
    monkeypatch.setattr(
        _rs, "get_runtime_features",
        lambda: Features(enable_legacy_inference=True),
    )
    _seed_store(tmp_settings)
    case_id = f"LC_f1234567_0002"
    leaf_id = next(
        n.node_id for n in stage1_normalize.normalize(PROJECT).xmind_leaves
        if n.title == "金额>0"
    )
    chat = _make_chat_returning([
        {
            "type": "business_rule", "content": "登录成功跳转首页",
            "module": "账号",
            "source_kind": "case", "source_ref": case_id,
            "confidence": 0.85, "reasoning": "",
        },
        {
            "type": "boundary", "content": "金额必须 > 0",
            "module": "支付",
            "source_kind": "xmind", "source_ref": leaf_id,
            "confidence": 0.9, "reasoning": "",
        },
    ])
    res = runner.run(PROJECT, cfg=LLMConfig(), chat_fn=chat)
    assert res.llm_calls > 0
    assert res.aggregated_count >= 1
    assert res.inferred_count >= 1
    assert legacy_store.load_inferred_kps(PROJECT)
