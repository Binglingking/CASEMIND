"""历史用例 / 历史 XMind 上传与读取的服务层。

设计要点（与 review 一致）：
  - file_id = sha1(file_bytes)[:8] —— 重传完全相同字节 → 幂等
  - 已存在 file_id 直接返回 already_parsed=True，前端给 toast，不重新解析
  - 列映射首次上传新表头时要求 UI 确认；同指纹（headers 集合）的后续文件复用映射
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from backend.core.legacy import legacy_store
from backend.core.legacy._hash import bytes_content_id
from backend.core.legacy.column_mapper import (
    auto_map,
    header_fingerprint,
    needs_ai_assist,
)
from backend.core.legacy.excel_parser import parse_excel
from backend.core.legacy.xmind_parser import parse_any as parse_xmind_any
from backend.core.timeutil import utc_iso_z
from backend.schemas.column_mapping import ColumnMapping
from backend.schemas.legacy_case import LegacyCase, LegacyCaseFile
from backend.schemas.test_case import CaseStep, SourceRef, TestCase

logger = logging.getLogger(__name__)


SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_\-.一-龥]+")


def _sanitize_name(name: str) -> str:
    base = Path(name).name
    base = SAFE_NAME_RE.sub("_", base).strip("._-") or "legacy"
    return base[:128]


# ============ 历史用例 ============

@dataclass
class ExcelIngestResult:
    file_id: str
    already_parsed: bool
    case_count: int
    sheet_names: list[str]
    column_mapping: ColumnMapping
    fingerprint: str
    needs_user_confirm: bool                    # 列映射命中率不足或首次见此指纹
    warnings: list[dict]                        # ParseWarning.model_dump 列表


def peek_excel_headers(content: bytes, filename: str) -> tuple[list[str], list[str]]:
    """只读表头与 sheet 名，不落盘也不入库。

    给 UI"列映射确认"弹窗用。
    """
    import io

    import pandas as pd

    bio = io.BytesIO(content)
    xl = pd.ExcelFile(bio)
    sheets = list(xl.sheet_names)
    headers: list[str] = []
    if sheets:
        df = xl.parse(sheets[0], dtype=str, nrows=0)
        headers = [str(c) for c in df.columns]
    return headers, sheets


def ingest_excel(
    project: str,
    filename: str,
    content: bytes,
    *,
    confirmed_mapping: ColumnMapping | None = None,
) -> ExcelIngestResult:
    """幂等上传一份 Excel 用例。

    Parameters
    ----------
    confirmed_mapping : ColumnMapping, optional
        UI 上确认过的映射；不传时使用自动推断。
        命中率 < 阈值且无 confirmed_mapping → 返回 needs_user_confirm=True，
        cases 不会被解析，调用方需重新带 confirmed_mapping 上传。
    """
    fid = bytes_content_id(content)

    # 幂等命中：同字节内容已解析
    existing = next(
        (f for f in legacy_store.list_case_files(project) if f.file_id == fid),
        None,
    )
    if existing is not None:
        return ExcelIngestResult(
            file_id=fid,
            already_parsed=True,
            case_count=existing.case_count,
            sheet_names=existing.sheet_names,
            column_mapping=ColumnMapping(
                header_to_standard=existing.column_mapping_used or {},
                hit_ratio=1.0,
                confirmed=True,
            ),
            fingerprint=header_fingerprint(list((existing.column_mapping_used or {}).keys())),
            needs_user_confirm=False,
            warnings=[w.model_dump() if hasattr(w, "model_dump") else dict(w)
                      for w in existing.parse_warnings],
        )

    # 落原始字节
    safe_name = _sanitize_name(filename)
    raw_dir = legacy_store.legacy_dir(project) / "raw"
    raw_path = raw_dir / f"{fid}{Path(safe_name).suffix.lower()}"
    raw_path.write_bytes(content)

    # 读表头 → 决定走哪份映射
    headers, sheet_names = peek_excel_headers(content, safe_name)
    fp = header_fingerprint(headers)
    store_obj = legacy_store.load_column_mapping_store(project)

    mapping: ColumnMapping
    if confirmed_mapping is not None:
        mapping = confirmed_mapping
        mapping.confirmed = True
        store_obj.by_fingerprint[fp] = mapping
        legacy_store.save_column_mapping_store(project, store_obj)
    elif fp in store_obj.by_fingerprint and store_obj.by_fingerprint[fp].confirmed:
        mapping = store_obj.by_fingerprint[fp]
    else:
        auto = auto_map(headers, extra_synonyms=store_obj.extra_synonyms)
        if needs_ai_assist(auto) and not (fp in store_obj.by_fingerprint):
            # 命中率不足，回到调用方让用户确认
            return ExcelIngestResult(
                file_id=fid,
                already_parsed=False,
                case_count=0,
                sheet_names=sheet_names,
                column_mapping=auto,
                fingerprint=fp,
                needs_user_confirm=True,
                warnings=[],
            )
        mapping = auto
        # 自动推断成功，保存到store（但未确认）
        if fp not in store_obj.by_fingerprint:
            store_obj.by_fingerprint[fp] = mapping
            legacy_store.save_column_mapping_store(project, store_obj)

    # 解析
    cases, sheet_names_real, warnings = parse_excel(
        raw_path, mapping,
        stage_suffixes=store_obj.stage_suffixes,
        file_id=fid,
    )

    meta = LegacyCaseFile(
        file_id=fid,
        name=safe_name,
        ext=raw_path.suffix.lower(),
        size=len(content),
        mtime=float(raw_path.stat().st_mtime),
        uploaded_at=utc_iso_z(),
        case_count=len(cases),
        sheet_names=sheet_names_real,
        column_mapping_used=mapping.header_to_standard,
        parse_warnings=warnings,
    )
    legacy_store.upsert_case_file(project, meta, cases)

    return ExcelIngestResult(
        file_id=fid,
        already_parsed=False,
        case_count=len(cases),
        sheet_names=sheet_names_real,
        column_mapping=mapping,
        fingerprint=fp,
        needs_user_confirm=False,
        warnings=[w.model_dump() for w in warnings],
    )


def list_excel_files(project: str) -> list[dict]:
    return [f.model_dump() for f in legacy_store.list_case_files(project)]


def list_excel_cases(project: str, file_id: str) -> list[dict]:
    return [c.model_dump() for c in legacy_store.load_cases(project, file_id)]


def delete_excel_file(project: str, file_id: str) -> dict:
    legacy_store.delete_case_file(project, file_id)
    return {"ok": True, "file_id": file_id}


# ============ 历史 XMind ============

@dataclass
class XMindIngestResult:
    file_id: str
    already_parsed: bool
    node_count: int
    leaf_count: int
    warnings: list[dict]


def ingest_xmind(
    project: str,
    filename: str,
    content: bytes,
) -> XMindIngestResult:
    """幂等上传一份 .xmind / .md。"""
    fid = bytes_content_id(content)

    existing = next(
        (f for f in legacy_store.list_xmind_files(project) if f.get("file_id") == fid),
        None,
    )
    if existing is not None:
        tree = legacy_store.load_xmind_tree(project, fid)
        return XMindIngestResult(
            file_id=fid,
            already_parsed=True,
            node_count=existing.get("node_count", 0),
            leaf_count=len(tree.leaves()) if tree else 0,
            warnings=[w.model_dump() if hasattr(w, "model_dump") else dict(w)
                      for w in (tree.parse_warnings if tree else [])],
        )

    safe_name = _sanitize_name(filename)
    raw_dir = legacy_store.legacy_dir(project) / "raw"
    raw_path = raw_dir / f"{fid}{Path(safe_name).suffix.lower()}"
    raw_path.write_bytes(content)

    tree = parse_xmind_any(raw_path, file_id=fid)
    # 用安全文件名覆盖 path.name
    tree.name = safe_name

    legacy_store.upsert_xmind_tree(project, tree)

    return XMindIngestResult(
        file_id=fid,
        already_parsed=False,
        node_count=len(tree.nodes),
        leaf_count=len(tree.leaves()),
        warnings=[w.model_dump() for w in tree.parse_warnings],
    )


def list_xmind_files(project: str) -> list[dict]:
    return legacy_store.list_xmind_files(project)


def get_xmind_tree(project: str, file_id: str) -> dict | None:
    tree = legacy_store.load_xmind_tree(project, file_id)
    return tree.model_dump() if tree else None


def delete_xmind_file(project: str, file_id: str) -> dict:
    legacy_store.delete_xmind_file(project, file_id)
    return {"ok": True, "file_id": file_id}


# ============ 反哺候选审核 ============

def list_inferred(project: str, status: str | None = None) -> list[dict]:
    items = legacy_store.load_inferred_kps(project)
    if status:
        items = [i for i in items if i.review_status == status]
    return [i.model_dump() for i in items]


def review_inferred(
    project: str,
    inferred_id: str,
    decision: str,
    reviewer: str = "",
) -> dict:
    """decision: 'accept' | 'reject'。
    accept 仅改状态为 accepted；真正写入 knowledge_points.json 由
    Memory 模块的合并入口负责（不在此服务内自动合并）。
    """
    if decision not in ("accept", "reject"):
        raise ValueError("decision must be 'accept' or 'reject'")
    items = legacy_store.load_inferred_kps(project)
    target = next((i for i in items if i.inferred_id == inferred_id), None)
    if target is None:
        raise ValueError(f"inferred_id 不存在: {inferred_id}")
    target.review_status = "accepted" if decision == "accept" else "rejected"
    target.reviewed_at = utc_iso_z()
    target.reviewed_by = reviewer or None
    legacy_store.save_inferred_kps(project, items)
    return target.model_dump()


def batch_review_inferred(
    project: str,
    inferred_ids: list[str],
    decision: str,
    reviewer: str = "",
) -> list[dict]:
    """批量审核反哺候选。
    
    Parameters
    ----------
    inferred_ids : list[str]
        要审核的反哺候选ID列表
    decision : str
        'accept' | 'reject'
    reviewer : str
        审核人
        
    Returns
    -------
    list[dict]
        审核结果列表
    """
    if decision not in ("accept", "reject"):
        raise ValueError("decision must be 'accept' or 'reject'")
    
    items = legacy_store.load_inferred_kps(project)
    results = []
    
    for inferred_id in inferred_ids:
        target = next((i for i in items if i.inferred_id == inferred_id), None)
        if target is None:
            # 如果某个ID不存在，跳过它
            continue
        
        target.review_status = "accepted" if decision == "accept" else "rejected"
        target.reviewed_at = utc_iso_z()
        target.reviewed_by = reviewer or None
        results.append(target.model_dump())
    
    # 保存更新后的所有项目
    legacy_store.save_inferred_kps(project, items)
    return results


def promote_accepted_inferred(project: str) -> dict:
    """将 accepted / auto_accepted 的 InferredKnowledgePoint 提升为正式 KnowledgePoint。

    读取 inferred_kps.json 中 review_status 为 'accepted' 或 'auto_accepted' 且
    promoted_kp_id 为空的条目，转换为 KnowledgePoint 并写入 knowledge_points.json。

    此函数设计为幂等：已提升的条目（promoted_kp_id 非空）会被跳过。

    Returns
    -------
    dict  {"promoted_count": int, "kp_ids": list[str], "skipped_already_promoted": int}
    """
    from backend.core import kp_store
    from backend.schemas.knowledge_point import KnowledgePoint, KPSource

    inferred = legacy_store.load_inferred_kps(project)
    accepted = [i for i in inferred
                if i.review_status in ("accepted", "auto_accepted") and not i.promoted_kp_id]

    if not accepted:
        return {
            "promoted_count": 0,
            "kp_ids": [],
            "skipped_already_promoted": len(
                [i for i in inferred
                 if i.review_status in ("accepted", "auto_accepted") and i.promoted_kp_id]
            ),
        }

    now = utc_iso_z()
    new_kps: list[KnowledgePoint] = []

    for ikp in accepted:
        kp_id = kp_store.next_kp_id(project, ikp.module, ikp.type)

        # 构造溯源信息：优先使用聚合源列表
        source_label = ikp.source.file or f"legacy:{ikp.source.file_id}"
        source_detail_parts = [f"legacy_inferred:{ikp.inferred_id}"]
        if ikp.aggregated_from:
            source_detail_parts.append(f"aggregated_from:{len(ikp.aggregated_from)}sources")
        if ikp.source.case_id:
            source_detail_parts.append(f"case:{ikp.source.case_id}")
        if ikp.source.case_row is not None:
            source_detail_parts.append(f"row:{ikp.source.case_row}")
        if ikp.source.node_path:
            source_detail_parts.append(f"path:{'/'.join(ikp.source.node_path)}")
        chunk_id = "|".join(source_detail_parts)

        # section 字段放入 AI 总结依据（如果存在）
        section_info = f"来源: {ikp.source.kind} / 置信度: {ikp.confidence}"
        if ikp.source_summary:
            section_info += f" / 总结: {ikp.source_summary[:120]}"

        new_kps.append(KnowledgePoint(
            kp_id=kp_id,
            type=ikp.type,
            content=ikp.content,
            module=ikp.module,
            aliases=ikp.aliases,
            source=KPSource(
                file=source_label,
                chunk_id=chunk_id,
                section=section_info,
            ),
            doc_version=ikp.extracted_at[:10],
            confidence=ikp.confidence,
            extracted_at=now,
            edited_by_user=False,
            orphan=False,
        ))
        ikp.promoted_kp_id = kp_id

    # 写入 knowledge_points.json
    existing = kp_store.load_all(project)
    kp_store.save_all(project, existing + new_kps)

    # 回写 inferred_kps.json（更新 promoted_kp_id，保证下次幂等跳过）
    legacy_store.save_inferred_kps(project, inferred)

    logger.info(
        "[legacy] promote_accepted_inferred project=%s promoted=%d",
        project, len(new_kps),
    )

    return {
        "promoted_count": len(new_kps),
        "kp_ids": [kp.kp_id for kp in new_kps],
        "skipped_already_promoted": len(
            [i for i in inferred
             if i.review_status in ("accepted", "auto_accepted") and i.promoted_kp_id]
        ),
    }


def revoke_auto_accepted(project: str, inferred_id: str) -> dict | None:
    """撤销 AI 自动通过的候选，将其重置为 pending 状态供人工重新审核。

    仅对 review_status='auto_accepted' 的条目有效；已人工 accept 的不受影响。
    """
    items = legacy_store.load_inferred_kps(project)
    target = next((i for i in items if i.inferred_id == inferred_id), None)
    if target is None:
        return None
    if target.review_status != "auto_accepted":
        raise ValueError(
            f"只能撤销 auto_accepted 状态，当前为 {target.review_status}"
        )
    target.review_status = "pending"
    target.auto_accepted = False
    target.reviewed_by = None
    target.reviewed_at = None
    legacy_store.save_inferred_kps(project, items)
    logger.info("[legacy] revoke_auto_accepted %s → pending", inferred_id)
    return target.model_dump()


def update_inferred_content(
    project: str, inferred_id: str, content: str,
    editor: str = "",
) -> dict | None:
    """用户二次编辑反哺候选的内容（适用于 auto_accepted 和 accepted）。"""
    items = legacy_store.load_inferred_kps(project)
    target = next((i for i in items if i.inferred_id == inferred_id), None)
    if target is None:
        return None
    target.content = content[:300]
    target.reviewed_by = editor or target.reviewed_by
    target.reviewed_at = utc_iso_z()
    legacy_store.save_inferred_kps(project, items)
    logger.info("[legacy] update_inferred_content %s", inferred_id)
    return target.model_dump()


# ============ Mention 解析（取代 reference_service） ============

def _truncate(text: str, max_chars: int = 40000) -> tuple[str, bool]:
    if len(text) > max_chars:
        return text[:max_chars], True
    return text, False


def resolve_legacy_case_mention(project: str, file_id: str) -> dict | None:
    """把一份历史用例 Excel 渲染为 prompt 注入文本。"""
    files = legacy_store.list_case_files(project)
    meta = next((f for f in files if f.file_id == file_id), None)
    if meta is None:
        return None
    cases = legacy_store.load_cases(project, file_id)
    lines = [f"# 历史用例：{meta.name}"]
    for c in cases:
        lines.append(f"\n## {c.case_id}  {c.title}")
        if c.module or c.sub_item:
            lines.append(f"模块/子项：{c.module} / {c.sub_item}")
        if c.preconditions:
            lines.append(f"前置：{c.preconditions}")
        for s in c.steps:
            lines.append(f"  {s.index}. {s.action} → {s.expected}")
    text, truncated = _truncate("\n".join(lines))
    return {
        "label": meta.name,
        "name": meta.name,
        "content": text,
        "truncated": truncated,
        "size": meta.size,
    }


# ============ Few-shot 检索（供 case_gen 流水线调用） ============

_PRIORITY_MAP = {
    "P0": "P0", "P1": "P1", "P2": "P2", "P3": "P3",
    "高": "P0", "中": "P1", "低": "P2",
    "高优": "P0", "高优先级": "P0", "中优": "P1", "低优": "P2",
}


def _legacy_priority_to_pmap(p: str) -> str:
    if not p:
        return "P2"
    return _PRIORITY_MAP.get(p.strip(), "P2")


_EXCEPTION_KWS = ("异常", "失败", "错误", "exception", "fail", "error")
_BOUNDARY_KWS = ("边界", "boundary", "极限", "最大", "最小")
_SECURITY_KWS = ("安全", "权限", "鉴权", "security", "auth", "越权")
_PERF_KWS = ("性能", "并发", "压测", "perf", "load")
_COMPAT_KWS = ("兼容", "compat", "版本")


def _infer_category(stage: str | None, title: str) -> str:
    text = f"{stage or ''} {title}".lower()
    if any(k in text for k in _EXCEPTION_KWS):
        return "异常"
    if any(k in text for k in _BOUNDARY_KWS):
        return "边界"
    if any(k in text for k in _SECURITY_KWS):
        return "安全"
    if any(k in text for k in _PERF_KWS):
        return "性能"
    if any(k in text for k in _COMPAT_KWS):
        return "兼容"
    return "正常"


def _legacy_to_testcase(lc: LegacyCase) -> TestCase | None:
    """LegacyCase → TestCase（仅用于 few-shot prompt，不入 cases.json）。

    占位 source_refs 用 `chunk_id=legacy:<file_id>:<row>`，标记来源便于追溯。
    任一字段越界（title 超 30/step.action 超 200/expected 超 500）都安全截断。
    """
    case_steps: list[CaseStep] = []
    for s in lc.steps:
        action = (s.action or "").strip()[:200] or "(空)"
        case_steps.append(CaseStep(step=s.index, action=action, data=""))
    if not case_steps:
        case_steps = [CaseStep(step=1, action="(无步骤)", data="")]

    expected = ""
    for s in lc.steps:
        if s.expected:
            expected = s.expected.strip()[:500]
            break

    title = (lc.title or "(未命名)").strip()
    if len(title) > 30:
        title = title[:29] + "…"

    fid_token = (lc.case_id.split("_")[1] if "_" in lc.case_id else "x")[:6]
    src = SourceRef(
        chunk_id=f"legacy:{fid_token}:{lc.source_row}",
        file=lc.source_file,
        section=lc.module or None,
    )

    try:
        return TestCase(
            case_id=lc.case_id,
            title=title,
            priority=_legacy_priority_to_pmap(lc.priority),
            category=_infer_category(lc.stage, lc.title),
            feature_point="legacy",                  # 占位；few-shot 注入时由 generator 强制对齐
            preconditions=[lc.preconditions] if lc.preconditions else [],
            steps=case_steps,
            expected_result=expected or "(预期未提供)",
            source_refs=[src],
            generated_by="legacy_import",
            confidence=0.7,
            created_at=utc_iso_z(),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[legacy_few_shot] TestCase 合成失败 case_id=%s: %r", lc.case_id, e)
        return None


def select_legacy_few_shot(
    project: str,
    *,
    module: str = "",
    sub_item_base: str = "",
    stage: str | None = None,
    limit: int = 3,
) -> list[TestCase]:
    """按 (module, sub_item_base, stage) 在历史用例里挑相似样例。

    匹配优先级：
      1. module + sub_item_base + stage 全等
      2. module + sub_item_base
      3. module
      4. 任意（兜底）
    截断到 limit 条；任意一条转换失败跳过，不影响其它。
    """
    pool = legacy_store.all_cases(project)
    if not pool:
        return []

    def _match(level: int, c: LegacyCase) -> bool:
        if level == 1:
            # 显式 stage 才参与匹配；stage=None → 跳过 level1，回退到 level2
            if stage is None:
                return False
            return (
                bool(module) and c.module == module
                and bool(sub_item_base) and c.sub_item_base == sub_item_base
                and stage == (c.stage or "")
            )
        if level == 2:
            return (
                bool(module) and c.module == module
                and bool(sub_item_base) and c.sub_item_base == sub_item_base
            )
        if level == 3:
            return bool(module) and c.module == module
        return True

    # 硬边界：从最严格层级往下，第一个非空层级就停止；避免不相关样例污染 prompt。
    selected: list[LegacyCase] = []
    for level in (1, 2, 3, 4):
        bucket = [c for c in pool if _match(level, c)]
        if bucket:
            selected = bucket[:limit]
            break

    out: list[TestCase] = []
    for lc in selected:
        tc = _legacy_to_testcase(lc)
        if tc is not None:
            out.append(tc)
    return out


def resolve_legacy_xmind_mention(project: str, file_id: str) -> dict | None:
    tree = legacy_store.load_xmind_tree(project, file_id)
    if tree is None:
        return None
    lines = [f"# 历史 XMind：{tree.name}"]
    for n in tree.nodes:
        indent = "  " * n.depth
        lines.append(f"{indent}- {n.title}")
    text, truncated = _truncate("\n".join(lines))
    return {
        "label": tree.name,
        "name": tree.name,
        "content": text,
        "truncated": truncated,
        "size": tree.size,
    }
