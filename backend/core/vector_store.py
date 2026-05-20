"""Vector store — one index per (project, namespace).

Prefers FAISS when available, falls back to a pure-NumPy cosine similarity
store so the app runs out-of-the-box on Windows / Python 3.12 where faiss
wheels may be unavailable.

扩展（PR1 起）：
  - StoredChunk 新增 namespace / version / metadata 字段，全部向后兼容加载
  - VectorStore 构造接受 namespace，默认 "chunks"
  - namespace="chunks" 沿用原文件名（<project>.faiss），零迁移
  - 其他 namespace 走 <project>.<namespace>.faiss 命名
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from backend.config import settings
from backend.core import embeddings as emb

try:
    import faiss  # type: ignore
    _HAS_FAISS = True
except Exception:
    faiss = None  # type: ignore
    _HAS_FAISS = False


DEFAULT_NAMESPACE = "chunks"
INDEX_VERSION = "v1"


@dataclass
class StoredChunk:
    id: str
    text: str
    source: str
    index: int
    # --- 以下字段为 PR1 新增，全部带默认值，旧 meta.jsonl 加载时自动补齐 ---
    namespace: str = DEFAULT_NAMESPACE
    version: str = INDEX_VERSION
    metadata: dict = field(default_factory=dict)
    # metadata 推荐键：
    #   module / type / doc_version / section / kp_id（namespace=knowledge_points 时必填）


class VectorStore:
    """Unified interface; internal backend is FAISS or NumPy.

    Parameters
    ----------
    project : str
        项目名。
    namespace : str
        索引命名空间。默认 "chunks" 沿用旧文件名；其他命名空间走
        <project>.<namespace>.* 新命名，与旧索引文件并存。
    """

    def __init__(self, project: str, namespace: str = DEFAULT_NAMESPACE):
        self.project = project
        self.namespace = namespace
        self.index_path, self.npy_path, self.meta_path = _paths(project, namespace)
        self._faiss_index = None             # faiss.Index when using faiss
        self._matrix: np.ndarray | None = None  # (N, D) when using numpy
        self._meta: list[StoredChunk] = []
        self._load()

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def _load(self):
        if _HAS_FAISS and self.index_path.exists():
            self._faiss_index = faiss.read_index(str(self.index_path))
        elif self.npy_path.exists():
            try:
                self._matrix = np.load(self.npy_path)
            except Exception:
                self._matrix = None

        if self.meta_path.exists():
            self._meta = []
            for line in self.meta_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                data = json.loads(line)
                # 向后兼容：旧记录缺 namespace/version/metadata，用当前 namespace 兜底
                data.setdefault("namespace", self.namespace)
                data.setdefault("version", INDEX_VERSION)
                data.setdefault("metadata", {})
                # 未知字段（未来可能加）直接丢弃，不让 dataclass 报错
                known = {"id", "text", "source", "index", "namespace", "version", "metadata"}
                data = {k: v for k, v in data.items() if k in known}
                self._meta.append(StoredChunk(**data))

    def _save(self):
        if _HAS_FAISS and self._faiss_index is not None:
            faiss.write_index(self._faiss_index, str(self.index_path))
        elif self._matrix is not None:
            np.save(self.npy_path, self._matrix)
        with self.meta_path.open("w", encoding="utf-8") as f:
            for m in self._meta:
                f.write(json.dumps(asdict(m), ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def has_source(self, source: str) -> bool:
        return any(m.source == source for m in self._meta)

    def remove_source(self, source: str):
        keep_idx = [i for i, m in enumerate(self._meta) if m.source != source]
        if len(keep_idx) == len(self._meta):
            return
        remaining = [self._meta[i] for i in keep_idx]
        # rebuild index from scratch
        self._meta = []
        self._faiss_index = None
        self._matrix = None
        if remaining:
            texts = [c.text for c in remaining]
            vecs = emb.embed(texts)
            self._init_index(vecs.shape[1])
            self._add_vectors(vecs)
            self._meta = remaining
        self._save()

    def add_chunks(self, chunks: list, metadata_fn=None) -> int:
        """向索引追加 chunks。

        Parameters
        ----------
        chunks : list
            由 chunker.chunk_text 产生的 Chunk（含 text / source / index）。
        metadata_fn : Optional[Callable[[Chunk], dict]]
            可选回调：对每个 Chunk 生成 metadata 字典。不提供则 metadata={}。
            用于在 KP / HybridRetriever 等场景挂载 module / type 等过滤维度。
        """
        if not chunks:
            return 0
        texts = [c.text for c in chunks]
        vecs = emb.embed(texts)
        if self._faiss_index is None and self._matrix is None:
            self._init_index(vecs.shape[1])
        self._add_vectors(vecs)
        base = len(self._meta)
        for i, c in enumerate(chunks):
            md = metadata_fn(c) if metadata_fn else {}
            self._meta.append(StoredChunk(
                id=f"{c.source}::{c.index}::{base+i}",
                text=c.text,
                source=c.source,
                index=c.index,
                namespace=self.namespace,
                version=INDEX_VERSION,
                metadata=md,
            ))
        self._save()
        return len(chunks)

    def search(self, query: str, top_k: int = 6) -> list[tuple[StoredChunk, float]]:
        total = self._ntotal()
        if total == 0:
            return []
        vec = emb.embed([query])  # already L2-normalized
        k = min(top_k, total)

        if _HAS_FAISS and self._faiss_index is not None:
            scores, idxs = self._faiss_index.search(vec, k)
            scores, idxs = scores[0], idxs[0]
        else:
            # cosine == dot since both sides are normalized
            sims = (self._matrix @ vec[0]).astype("float32")
            idxs = np.argsort(-sims)[:k]
            scores = sims[idxs]

        out: list[tuple[StoredChunk, float]] = []
        for i, s in zip(idxs, scores):
            i = int(i)
            if i < 0 or i >= len(self._meta):
                continue
            out.append((self._meta[i], float(s)))
        return out

    def all_chunks(self) -> list[StoredChunk]:
        """返回索引内全量 StoredChunk 的只读引用（供 BM25 建索引、覆盖率计算用）。"""
        return list(self._meta)

    def stats(self) -> dict:
        sources = sorted({m.source for m in self._meta})
        return {
            "project": self.project,
            "namespace": self.namespace,
            "chunks": len(self._meta),
            "sources": sources,
            "vectors": self._ntotal(),
            "backend": "faiss" if _HAS_FAISS else "numpy",
        }

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _init_index(self, dim: int):
        if _HAS_FAISS:
            self._faiss_index = faiss.IndexFlatIP(dim)
        else:
            self._matrix = np.zeros((0, dim), dtype="float32")

    def _add_vectors(self, vecs: np.ndarray):
        if _HAS_FAISS and self._faiss_index is not None:
            self._faiss_index.add(vecs)
        else:
            if self._matrix is None:
                self._matrix = vecs.astype("float32")
            else:
                self._matrix = np.vstack([self._matrix, vecs.astype("float32")])

    def _ntotal(self) -> int:
        if _HAS_FAISS and self._faiss_index is not None:
            return int(self._faiss_index.ntotal)
        if self._matrix is not None:
            return int(self._matrix.shape[0])
        return 0


def _paths(project: str, namespace: str) -> tuple[Path, Path, Path]:
    """计算 (index_path, npy_path, meta_path) —— 默认 namespace 保留旧文件名。"""
    if namespace == DEFAULT_NAMESPACE:
        return (
            settings.vector_dir / f"{project}.faiss",
            settings.vector_dir / f"{project}.npy",
            settings.vector_dir / f"{project}.meta.jsonl",
        )
    return (
        settings.vector_dir / f"{project}.{namespace}.faiss",
        settings.vector_dir / f"{project}.{namespace}.npy",
        settings.vector_dir / f"{project}.{namespace}.meta.jsonl",
    )
