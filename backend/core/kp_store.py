"""知识点（KnowledgePoint）持久化。

文件布局（见 docs/design/01 §3.3）：

    memory/<project>/
    ├── knowledge_points.json         # KnowledgePoint[] 全量
    ├── knowledge_points.seq.json     # {module: {type_abbrev: int}} 序号
    └── kp_cache/
        └── <chunk_id_safe>.json      # 单 chunk 的抽取缓存（幂等键 = content_hash）

职责严格限定：纯 IO + ID 生成 + 合并规则，不调用 LLM、不做 schema 校验转换。
LLM 输出到 KnowledgePoint 的组装在 agents/knowledge_extractor.py 里完成。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pydantic import TypeAdapter, ValidationError

from backend.core.project import project_manager
from backend.schemas.knowledge_point import KnowledgePoint


KP_FILE = "knowledge_points.json"
SEQ_FILE = "knowledge_points.seq.json"
CACHE_DIR = "kp_cache"

# type -> 缩写（kp_id 里用）
TYPE_ABBR = {
    "business_rule": "br",
    "input_constraint": "ic",
    "boundary": "bd",
    "exception_flow": "ef",
    "acceptance_criteria": "ac",
    "api_spec": "as",
    "data_field": "df",
}

_SLUG_KEEP = re.compile(r"[A-Za-z0-9_\-一-鿿]+")


# ---- 路径辅助 --------------------------------------------------------------

def _kp_path(project: str) -> Path:
    return project_manager.mem_dir(project) / KP_FILE


def _seq_path(project: str) -> Path:
    return project_manager.mem_dir(project) / SEQ_FILE


def _cache_dir(project: str) -> Path:
    d = project_manager.mem_dir(project) / CACHE_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _chunk_id_safe(chunk_id: str) -> str:
    """chunk_id 里有 '::' 和 '/'，转成安全文件名。"""
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", chunk_id)[:120]


def cache_path(project: str, chunk_id: str) -> Path:
    return _cache_dir(project) / f"{_chunk_id_safe(chunk_id)}.json"


def error_cache_path(project: str, chunk_id: str) -> Path:
    return _cache_dir(project) / f"{_chunk_id_safe(chunk_id)}.error.json"


# ---- 序号与 kp_id 生成 -----------------------------------------------------

def _module_slug(module: str) -> str:
    """模块名做简单 slug：保留中英数，空格转 '-'，截 16 字符。"""
    parts = _SLUG_KEEP.findall(module or "")
    s = "-".join(parts) if parts else "未分类"
    return s[:16]


def load_seq(project: str) -> dict[str, dict[str, int]]:
    p = _seq_path(project)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_seq(project: str, seq: dict[str, dict[str, int]]) -> None:
    _seq_path(project).write_text(
        json.dumps(seq, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def next_kp_id(project: str, module: str, kp_type: str) -> str:
    """原子地拿下一个 kp_id 并持久化。

    规则：KP_{module_slug}_{type_abbr}_{seq:04d}
    """
    abbr = TYPE_ABBR.get(kp_type)
    if not abbr:
        raise ValueError(f"未知 KP 类型: {kp_type}")
    slug = _module_slug(module)
    seq = load_seq(project)
    mod_bucket = seq.setdefault(slug, {})
    n = mod_bucket.get(abbr, 0) + 1
    mod_bucket[abbr] = n
    save_seq(project, seq)
    return f"KP_{slug}_{abbr}_{n:04d}"


# ---- KP 全量读写 -----------------------------------------------------------

_KP_ADAPTER = TypeAdapter(list[KnowledgePoint])


def load_all(project: str) -> list[KnowledgePoint]:
    p = _kp_path(project)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    try:
        return _KP_ADAPTER.validate_python(data)
    except ValidationError:
        # 一条坏的不应让全部丢失：逐条尝试
        out: list[KnowledgePoint] = []
        for item in data if isinstance(data, list) else []:
            try:
                out.append(KnowledgePoint.model_validate(item))
            except ValidationError:
                continue
        return out


def save_all(project: str, kps: Iterable[KnowledgePoint]) -> None:
    """原子写：先写 .tmp 再 rename，避免中途崩溃导致 json 损坏。"""
    p = _kp_path(project)
    data = [kp.model_dump() for kp in kps]
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


# ---- 合并规则（增量/全量重建通用） -----------------------------------------

@dataclass
class MergeStats:
    added: int = 0
    replaced: int = 0          # 来自同一 chunk 的旧 KP 被新抽取替换
    preserved_edited: int = 0  # 用户编辑过的 KP 保留不动
    orphaned: int = 0          # 源文件已不存在，标 orphan
    kept_other: int = 0        # 来自其他 chunk 的 KP 原样保留


def merge_kps(
    existing: list[KnowledgePoint],
    newly_extracted: list[KnowledgePoint],
    affected_chunk_ids: set[str],
    live_sources: set[str] | None = None,
) -> tuple[list[KnowledgePoint], MergeStats]:
    """把新抽取结果并入现有 KP 列表。

    核心规则：
      1. `affected_chunk_ids` 内、且 `edited_by_user=False` 的旧 KP 被替换；
      2. `edited_by_user=True` 的旧 KP 一律保留（用户手改不被 LLM 覆盖）；
      3. 源文件在 `live_sources` 之外的 KP 标 `orphan=True`（None 表示不做孤儿判定）；
      4. 其他 KP 原样保留。
    """
    stats = MergeStats()
    out: list[KnowledgePoint] = []
    for kp in existing:
        if kp.source.chunk_id in affected_chunk_ids and not kp.edited_by_user:
            stats.replaced += 1
            continue  # 将被新抽取替换
        # 孤儿判定
        if live_sources is not None and kp.source.file not in live_sources:
            if not kp.orphan:
                stats.orphaned += 1
                kp = kp.model_copy(update={"orphan": True})
        if kp.edited_by_user and kp.source.chunk_id in affected_chunk_ids:
            stats.preserved_edited += 1
        else:
            stats.kept_other += 1
        out.append(kp)
    for kp in newly_extracted:
        out.append(kp)
        stats.added += 1
    return out, stats


def find_by_id(project: str, kp_id: str) -> KnowledgePoint | None:
    for kp in load_all(project):
        if kp.kp_id == kp_id:
            return kp
    return None


def upsert_one(project: str, kp: KnowledgePoint) -> KnowledgePoint:
    """用户编辑场景：按 kp_id 替换或追加。"""
    all_kps = load_all(project)
    for i, existing in enumerate(all_kps):
        if existing.kp_id == kp.kp_id:
            all_kps[i] = kp
            save_all(project, all_kps)
            return kp
    all_kps.append(kp)
    save_all(project, all_kps)
    return kp


def delete_one(project: str, kp_id: str) -> bool:
    all_kps = load_all(project)
    left = [kp for kp in all_kps if kp.kp_id != kp_id]
    if len(left) == len(all_kps):
        return False
    save_all(project, left)
    return True


def clear_all(project: str) -> None:
    """全量重建准备：清 kp.json + seq + cache。保留 edited_by_user 的条目是调用方的事。"""
    for p in (_kp_path(project), _seq_path(project)):
        if p.exists():
            p.unlink()
    cdir = project_manager.mem_dir(project) / CACHE_DIR
    if cdir.exists():
        for f in cdir.glob("*"):
            try:
                f.unlink()
            except OSError:
                pass
