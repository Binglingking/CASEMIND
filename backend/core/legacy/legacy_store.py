"""legacy/ 目录的读写门面。

布局：
  memory/<project>/legacy/
    cases.json                  # list[LegacyCaseFile] 元数据
    cases/<file_id>.json        # 单文件解析后的 list[LegacyCase]
    xmind.json                  # list[ {file_id, name, ...} ] 元数据
    xmind/<file_id>.json        # 单棵 LegacyXMindTree
    raw/<file_id><ext>          # 原始上传文件副本（用于重新解析）
    column_mapping.json         # ProjectColumnMappingStore
    style_profile.json          # StyleProfile
    inferred_kps.json           # list[InferredKnowledgePoint]
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from backend.core.project import project_manager
from backend.schemas.column_mapping import ProjectColumnMappingStore
from backend.schemas.inferred_kp import InferredKnowledgePoint
from backend.schemas.legacy_case import LegacyCase, LegacyCaseFile
from backend.schemas.legacy_xmind import LegacyXMindTree
from backend.schemas.style_profile import StyleProfile


# ---- 路径 ----

def legacy_dir(project: str) -> Path:
    d = project_manager.mem_dir(project) / "legacy"
    d.mkdir(parents=True, exist_ok=True)
    (d / "cases").mkdir(parents=True, exist_ok=True)
    (d / "xmind").mkdir(parents=True, exist_ok=True)
    (d / "raw").mkdir(parents=True, exist_ok=True)
    return d


def _read_json(p: Path, default):
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---- 原始文件保存 ----

def save_raw(project: str, file_id: str, original: Path) -> Path:
    target = legacy_dir(project) / "raw" / f"{file_id}{original.suffix.lower()}"
    shutil.copyfile(original, target)
    return target


def get_raw_path(project: str, file_id: str, ext: str) -> Path | None:
    p = legacy_dir(project) / "raw" / f"{file_id}{ext.lower()}"
    return p if p.exists() else None


# ---- 历史用例 ----

def list_case_files(project: str) -> list[LegacyCaseFile]:
    raw = _read_json(legacy_dir(project) / "cases.json", [])
    out: list[LegacyCaseFile] = []
    for it in raw:
        try:
            out.append(LegacyCaseFile.model_validate(it))
        except Exception:
            continue
    return out


def save_case_files_index(project: str, files: list[LegacyCaseFile]) -> None:
    _write_json(
        legacy_dir(project) / "cases.json",
        [f.model_dump() for f in files],
    )


def upsert_case_file(project: str, meta: LegacyCaseFile, cases: list[LegacyCase]) -> None:
    files = [f for f in list_case_files(project) if f.file_id != meta.file_id]
    files.append(meta)
    save_case_files_index(project, files)
    _write_json(
        legacy_dir(project) / "cases" / f"{meta.file_id}.json",
        [c.model_dump() for c in cases],
    )


def load_cases(project: str, file_id: str) -> list[LegacyCase]:
    raw = _read_json(legacy_dir(project) / "cases" / f"{file_id}.json", [])
    out: list[LegacyCase] = []
    for it in raw:
        try:
            out.append(LegacyCase.model_validate(it))
        except Exception:
            continue
    return out


def delete_case_file(project: str, file_id: str) -> None:
    files = [f for f in list_case_files(project) if f.file_id != file_id]
    save_case_files_index(project, files)
    p = legacy_dir(project) / "cases" / f"{file_id}.json"
    if p.exists():
        p.unlink()
    # raw 副本不主动删，保留可重新解析；若用户要彻底清除，再加显式 API


def all_cases(project: str) -> list[LegacyCase]:
    out: list[LegacyCase] = []
    for f in list_case_files(project):
        out.extend(load_cases(project, f.file_id))
    return out


# ---- 历史 XMind ----

def list_xmind_files(project: str) -> list[dict]:
    return _read_json(legacy_dir(project) / "xmind.json", [])


def save_xmind_files_index(project: str, files: list[dict]) -> None:
    _write_json(legacy_dir(project) / "xmind.json", files)


def upsert_xmind_tree(project: str, tree: LegacyXMindTree) -> None:
    idx = [f for f in list_xmind_files(project) if f.get("file_id") != tree.file_id]
    idx.append({
        "file_id": tree.file_id,
        "name": tree.name,
        "ext": tree.ext,
        "size": tree.size,
        "mtime": tree.mtime,
        "uploaded_at": tree.uploaded_at,
        "node_count": len(tree.nodes),
        "analyzed": tree.analyzed,
        "analyzed_at": tree.analyzed_at,
    })
    save_xmind_files_index(project, idx)
    _write_json(
        legacy_dir(project) / "xmind" / f"{tree.file_id}.json",
        tree.model_dump(),
    )


def load_xmind_tree(project: str, file_id: str) -> LegacyXMindTree | None:
    raw = _read_json(legacy_dir(project) / "xmind" / f"{file_id}.json", None)
    if raw is None:
        return None
    try:
        return LegacyXMindTree.model_validate(raw)
    except Exception:
        return None


def delete_xmind_file(project: str, file_id: str) -> None:
    idx = [f for f in list_xmind_files(project) if f.get("file_id") != file_id]
    save_xmind_files_index(project, idx)
    p = legacy_dir(project) / "xmind" / f"{file_id}.json"
    if p.exists():
        p.unlink()


# ---- 列映射 ----

def load_column_mapping_store(project: str) -> ProjectColumnMappingStore:
    raw = _read_json(legacy_dir(project) / "column_mapping.json", None)
    if raw is None:
        return ProjectColumnMappingStore()
    try:
        return ProjectColumnMappingStore.model_validate(raw)
    except Exception:
        return ProjectColumnMappingStore()


def save_column_mapping_store(project: str, store: ProjectColumnMappingStore) -> None:
    _write_json(legacy_dir(project) / "column_mapping.json", store.model_dump())


# ---- 风格画像 ----

def load_style_profile(project: str) -> StyleProfile | None:
    raw = _read_json(legacy_dir(project) / "style_profile.json", None)
    if raw is None:
        return None
    try:
        return StyleProfile.model_validate(raw)
    except Exception:
        return None


def save_style_profile(project: str, profile: StyleProfile) -> None:
    _write_json(legacy_dir(project) / "style_profile.json", profile.model_dump())


# ---- 反哺候选 ----

_LEGACY_STATUS_MAP = {
    "pending": "pending_review",
    "accepted": "ready_to_build",
    "auto_accepted": "ready_to_build",
}


def _migrate_inferred_status(it: dict) -> dict:
    """旧 review_status 值 → 新三态。

    pending/accepted/auto_accepted 在 1.1 期间被重命名为
    pending_review/ready_to_build/promoted。已含 promoted_kp_id 的 accepted
    条目说明已经写入 knowledge_points.json → 直接标 promoted；
    其余 accepted/auto_accepted 进入 ready_to_build 队列。
    """
    status = it.get("review_status")
    if status in _LEGACY_STATUS_MAP:
        if status in ("accepted", "auto_accepted") and it.get("promoted_kp_id"):
            it["review_status"] = "promoted"
        else:
            it["review_status"] = _LEGACY_STATUS_MAP[status]
    return it


def load_inferred_kps(project: str) -> list[InferredKnowledgePoint]:
    raw = _read_json(legacy_dir(project) / "inferred_kps.json", [])
    out: list[InferredKnowledgePoint] = []
    for it in raw:
        try:
            out.append(InferredKnowledgePoint.model_validate(_migrate_inferred_status(it)))
        except Exception:
            continue
    return out


def save_inferred_kps(project: str, items: list[InferredKnowledgePoint]) -> None:
    _write_json(
        legacy_dir(project) / "inferred_kps.json",
        [i.model_dump() for i in items],
    )


def upsert_inferred_kps(project: str, items: list[InferredKnowledgePoint]) -> None:
    """按 inferred_id 覆盖式写入。"""
    existing = {i.inferred_id: i for i in load_inferred_kps(project)}
    for it in items:
        existing[it.inferred_id] = it
    save_inferred_kps(project, list(existing.values()))
