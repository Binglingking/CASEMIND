"""BM25 索引（每个 namespace 一份）。

设计约束（见 docs/design/02 §4.2）：
  - 用 rank_bm25.BM25Okapi，无 C 依赖，Windows/Py3.12 友好；
  - 文件命名：<project>.bm25.<namespace>.pkl；
  - 只 pickle `tokens: list[list[str]]`——不 pickle BM25Okapi 对象本身，
    避免 rank_bm25 版本升级后反序列化失败；
  - 索引顺序**与 VectorStore._meta 一一对应**；add_texts 时调用方负责保证两边同步；
  - BM25Okapi 无增量 API，add 后整体重建。
"""
from __future__ import annotations

import pickle
from pathlib import Path
from typing import Iterable

import numpy as np
from rank_bm25 import BM25Okapi

from backend.config import settings
from backend.core.tokenizer import tokenize, tokenize_many


def bm25_path(project: str, namespace: str) -> Path:
    return settings.vector_dir / f"{project}.bm25.{namespace}.pkl"


class BM25Index:
    """每个 (project, namespace) 一份 BM25 索引。

    基本不变式：`len(self._tokens)` 始终等于 VectorStore 里 `_meta` 的长度。
    调用方（HybridRetriever / add_chunks 调用链）负责维护这一点。
    """

    def __init__(self, project: str, namespace: str):
        self.project = project
        self.namespace = namespace
        self.path = bm25_path(project, namespace)
        self._tokens: list[list[str]] = []
        self._bm25: BM25Okapi | None = None
        self._load()

    # ---- 持久化 ---------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("rb") as f:
                data = pickle.load(f)
        except Exception:
            # 坏文件不让整个进程挂——清空在内存就好，下次 add/build 会覆盖
            self._tokens = []
            self._bm25 = None
            return
        tokens = data.get("tokens") if isinstance(data, dict) else None
        if not isinstance(tokens, list):
            self._tokens = []
            return
        self._tokens = [list(t) for t in tokens]
        self._refit()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("wb") as f:
            pickle.dump({"tokens": self._tokens, "version": "v1"}, f)
        tmp.replace(self.path)

    def _refit(self) -> None:
        """从 self._tokens 重新拟合 BM25Okapi。空语料返回 None，搜索端自行兜底。"""
        if not self._tokens:
            self._bm25 = None
            return
        # rank_bm25 不接受空文档；给空 tokens 的行塞一个占位 token，避免 div-by-zero
        safe = [t if t else ["__empty__"] for t in self._tokens]
        self._bm25 = BM25Okapi(safe)

    # ---- 读写 API -------------------------------------------------------

    def build(self, texts: list[str]) -> None:
        """从文本列表全量重建（丢弃旧 tokens）。"""
        self._tokens = tokenize_many(texts)
        self._refit()
        self._save()

    def add_texts(self, texts: Iterable[str]) -> None:
        """增量：追加文本并整体 refit。"""
        new_tokens = tokenize_many(list(texts))
        if not new_tokens:
            return
        self._tokens.extend(new_tokens)
        self._refit()
        self._save()

    def remove_indices(self, indices: Iterable[int]) -> None:
        """按下标移除（与 VectorStore.remove_source 对齐用）。"""
        drop = set(int(i) for i in indices)
        if not drop:
            return
        self._tokens = [t for i, t in enumerate(self._tokens) if i not in drop]
        self._refit()
        self._save()

    def clear(self) -> None:
        self._tokens = []
        self._bm25 = None
        if self.path.exists():
            self.path.unlink()

    def size(self) -> int:
        return len(self._tokens)

    # ---- 检索 -----------------------------------------------------------

    def search(self, query: str, top_k: int) -> list[tuple[int, float]]:
        """返回 [(meta_index, score), ...]，按 score 降序，只保留 score>0 的命中。

        meta_index 与 VectorStore._meta 的下标对齐。
        """
        if self._bm25 is None or top_k <= 0 or not self._tokens:
            return []
        q_tok = tokenize(query)
        if not q_tok:
            return []
        scores = self._bm25.get_scores(q_tok)
        k = min(top_k, len(scores))
        # argpartition 比 argsort 快；再对 top-k 内部排序
        if k <= 0:
            return []
        top_idx = np.argpartition(-scores, kth=min(k - 1, len(scores) - 1))[:k]
        ranked = sorted(top_idx, key=lambda i: -scores[int(i)])
        out: list[tuple[int, float]] = []
        for i in ranked:
            s = float(scores[int(i)])
            if s <= 0:
                continue
            out.append((int(i), s))
        return out
