"""Stage 4：全局聚合（纯函数）。

  - 跨批次同 (type + module + content) 的信号去重
  - 同 module 下相似度高的合并（先用简单字符串规范化判等，必要时再上 embedding）
  - 输出 module → contents 索引便于 UI 检索
"""
from __future__ import annotations

import re
from collections import defaultdict

from backend.agents.legacy_analyzer.schemas import (
    AggregatedSignals,
    ExtractedSignal,
)


_NORMALIZE_RE = re.compile(r"[\s　]+")


def _norm(s: str) -> str:
    return _NORMALIZE_RE.sub("", (s or "").strip().lower())


def aggregate(signals: list[ExtractedSignal]) -> AggregatedSignals:
    seen: dict[tuple[str, str, str], ExtractedSignal] = {}
    dropped = 0

    for s in signals:
        key = (s.type, _norm(s.module), _norm(s.content))
        if key in seen:
            dropped += 1
            # 保留 confidence 较高的一条
            if s.confidence > seen[key].confidence:
                seen[key] = s
        else:
            seen[key] = s

    items = list(seen.values())
    by_module: dict[str, list[str]] = defaultdict(list)
    for s in items:
        by_module[s.module].append(s.content)

    return AggregatedSignals(
        items=items,
        by_module=dict(by_module),
        duplicates_dropped=dropped,
    )
