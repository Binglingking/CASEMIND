"""Excel 列同义词匹配。

策略：
  1. 表头原文清洗（去空白、去标点、转小写）
  2. 同义词字典命中（内置 DEFAULT_SYNONYMS + 项目级 extra_synonyms）
  3. 编辑距离兜底（接近完全一致的拼写差异）
  4. 命中率 < AI_THRESHOLD 时由调用方决定要不要走 LLM 询问

不在本模块直接调 LLM；保持纯函数便于测试。
"""
from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

from backend.schemas.column_mapping import (
    ColumnMapping,
    DEFAULT_SYNONYMS,
    STANDARD_COLUMNS,
)


_CLEAN_RE = re.compile(r"[\s　\*\(\)\[\]【】（）:：·\-_,，.。/\\]+")

AI_THRESHOLD = 0.9                # hit_ratio 低于此值建议走 AI 兜底
FUZZY_RATIO = 0.85                # 编辑距离匹配阈值


def _clean(s: str) -> str:
    return _CLEAN_RE.sub("", (s or "").strip().lower())


def header_fingerprint(headers: list[str]) -> str:
    """同表头复用同一份映射的指纹。

    清洗后按字母序拼接 → sha1[:12]。
    """
    cleaned = sorted(_clean(h) for h in headers if h)
    raw = "|".join(cleaned).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def auto_map(
    headers: list[str],
    extra_synonyms: dict[str, list[str]] | None = None,
) -> ColumnMapping:
    """根据同义词字典对一组表头做自动映射。

    返回结果中 confirmed 永远为 False；调用方在用户确认后再翻为 True。
    """
    extra = extra_synonyms or {}
    # 构建反向索引：清洗后的别名 → 标准列名
    rev: dict[str, str] = {}
    for std in STANDARD_COLUMNS:
        merged: list[str] = list(DEFAULT_SYNONYMS.get(std, []))
        merged.extend(extra.get(std, []))
        for alias in merged:
            key = _clean(alias)
            if key:
                rev.setdefault(key, std)

    mapping: dict[str, str] = {}
    unmapped: list[str] = []
    matched_std: set[str] = set()

    for raw_h in headers:
        cleaned = _clean(raw_h)
        if not cleaned:
            mapping[raw_h] = ""
            unmapped.append(raw_h)
            continue

        # 1) 字典直接命中
        if cleaned in rev:
            std = rev[cleaned]
            mapping[raw_h] = std
            matched_std.add(std)
            continue

        # 2) 包含关系（清洗后包含或被包含）
        hit = ""
        for alias_clean, std in rev.items():
            if alias_clean and (alias_clean in cleaned or cleaned in alias_clean):
                hit = std
                break
        if hit:
            mapping[raw_h] = hit
            matched_std.add(hit)
            continue

        # 3) 编辑距离兜底
        best_ratio = 0.0
        best_std = ""
        for alias_clean, std in rev.items():
            r = SequenceMatcher(None, alias_clean, cleaned).ratio()
            if r > best_ratio:
                best_ratio = r
                best_std = std
        if best_ratio >= FUZZY_RATIO and best_std:
            mapping[raw_h] = best_std
            matched_std.add(best_std)
        else:
            mapping[raw_h] = ""
            unmapped.append(raw_h)

    hit_ratio = len(matched_std) / len(STANDARD_COLUMNS) if STANDARD_COLUMNS else 0.0
    return ColumnMapping(
        header_to_standard=mapping,
        unmapped_headers=unmapped,
        confirmed=False,
        hit_ratio=hit_ratio,
    )


def needs_ai_assist(mapping: ColumnMapping) -> bool:
    """命中率低于阈值时建议调用方调 LLM 补齐。"""
    return mapping.hit_ratio < AI_THRESHOLD
