"""混合检索：BM25 + Vector + RRF 融合 + 元数据过滤 + namespace 切换。

设计见 docs/design/02_hybrid_retrieval.md。

调用侧主要场景：
  - QueryAgent（feature flag on）：namespace="chunks"，不带 filters
  - 用例生成流水线（文档 03）：namespace="knowledge_points"，带 filters={"module": ..., "type": [...]}

实现原则：
  1. 两路各召回 top_k * 初始倍数，RRF 融合后再按 filters 过滤，最后截断到 top_k；
  2. 过滤不足 top_k 时不补召回（保守）——记录告警；
  3. BM25 索引缺失时**懒加载构建**：基于 VectorStore.all_chunks() 一次性重建；
  4. 单路退化：mode="vector" / "bm25" 时只走一路，RRF 退化为单路 rank 归一化。
"""
from __future__ import annotations

import fnmatch
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional

from backend.core.bm25_index import BM25Index
from backend.core.vector_store import StoredChunk, VectorStore
from backend.core import reranker as _reranker_mod


logger = logging.getLogger(__name__)


# RRF 常数，论文默认 60；见 docs/design/02 §6.2
RRF_K = 60
# 召回倍数：top_k * 这个倍数 作为每路的初始召回数
INITIAL_MULTIPLIER = 3
# 过滤率过高的告警阈值：过滤后不足 top_k 的比例
_FILTER_WARN_RATIO = 0.5


@dataclass
class SearchResult:
    chunk: StoredChunk
    score: float                     # RRF 后的融合得分
    score_breakdown: dict = field(default_factory=dict)
    # score_breakdown 键：
    #   vector: 向量余弦得分（未归一化）
    #   bm25:   BM25 原始得分
    #   rrf:    RRF 加和得分
    #   vector_rank / bm25_rank: 单路排名（0 起），未命中为 None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ------------- RRF 融合 ----------------------------------------------------

def rrf_merge(
    vector_hits: list[tuple[int, float]],
    bm25_hits: list[tuple[int, float]],
    k: int = RRF_K,
) -> list[tuple[int, dict]]:
    """双路 RRF 融合。

    返回 [(meta_idx, breakdown_dict), ...]，按 rrf 降序。
    """
    scores: dict[int, dict] = {}
    for rank, (idx, s) in enumerate(vector_hits):
        b = scores.setdefault(idx, {
            "vector": 0.0, "bm25": 0.0, "rrf": 0.0,
            "vector_rank": None, "bm25_rank": None,
        })
        b["vector"] = float(s)
        b["vector_rank"] = rank
        b["rrf"] += 1.0 / (k + rank + 1)
    for rank, (idx, s) in enumerate(bm25_hits):
        b = scores.setdefault(idx, {
            "vector": 0.0, "bm25": 0.0, "rrf": 0.0,
            "vector_rank": None, "bm25_rank": None,
        })
        b["bm25"] = float(s)
        b["bm25_rank"] = rank
        b["rrf"] += 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: -kv[1]["rrf"])


# ------------- filter 匹配 --------------------------------------------------

def match_filter(metadata: dict, filters: Optional[dict]) -> bool:
    """把 metadata 和 filters 做逐键比对。支持四种语义：

      - scalar 精确匹配：`{"module": "登录"}`
      - 列表 OR：`{"type": ["business_rule", "boundary"]}`
      - 字符串比较前缀 `>= / > / <= / <`：`{"doc_version": ">= 2025-01-01"}`
      - fnmatch 通配：`{"section": "3.2.*"}`

    未知键（metadata 里没有）视为不匹配；filters 为 None/空返回 True。
    """
    if not filters:
        return True
    for key, want in filters.items():
        got = metadata.get(key) if metadata else None
        if got is None:
            return False
        # 列表 → OR 匹配
        if isinstance(want, (list, tuple, set)):
            if got not in want:
                return False
            continue
        if isinstance(want, str) and isinstance(got, str):
            # 比较运算符
            for op in (">=", "<=", ">", "<"):
                if want.startswith(op):
                    rhs = want[len(op):].strip()
                    if not _compare(got, rhs, op):
                        return False
                    break
            else:
                # fnmatch 通配
                if any(c in want for c in "*?["):
                    if not fnmatch.fnmatchcase(got, want):
                        return False
                elif got != want:
                    return False
            continue
        # 数值等直接等值比较
        if got != want:
            return False
    return True


def _compare(got: str, rhs: str, op: str) -> bool:
    if op == ">=":
        return got >= rhs
    if op == "<=":
        return got <= rhs
    if op == ">":
        return got > rhs
    if op == "<":
        return got < rhs
    return False


# ------------- HybridRetriever ---------------------------------------------

class HybridRetriever:
    def __init__(self, project: str):
        self.project = project
        self._stores: dict[str, VectorStore] = {}
        self._bm: dict[str, BM25Index] = {}

    # ---- 懒加载 namespace 对应的两路索引 ----

    def _vs(self, namespace: str) -> VectorStore:
        vs = self._stores.get(namespace)
        if vs is None:
            vs = VectorStore(self.project, namespace=namespace)
            self._stores[namespace] = vs
        return vs

    def _bm25(self, namespace: str) -> BM25Index:
        """返回就绪的 BM25Index；若为空但 VectorStore 有数据，现场重建。"""
        bm = self._bm.get(namespace)
        if bm is None:
            bm = BM25Index(self.project, namespace)
            self._bm[namespace] = bm
        vs = self._vs(namespace)
        vs_size = len(vs.all_chunks())
        if bm.size() != vs_size:
            # 首次启用 hybrid / VectorStore 改过但 BM25 未同步 → 现场重建
            logger.info(
                "BM25 与 VectorStore 不同步（bm=%d, vs=%d），重建 [%s/%s]",
                bm.size(), vs_size, self.project, namespace,
            )
            bm.build([c.text for c in vs.all_chunks()])
        return bm

    # ---- 对外：搜索 ----

    def search(
        self,
        query: str,
        top_k: int = 8,
        namespace: str = "chunks",
        filters: Optional[dict] = None,
        mode: str = "hybrid",
        use_reranker: bool = False,
    ) -> list[SearchResult]:
        """混合检索入口。

        Parameters
        ----------
        query : str
            查询文本。
        top_k : int
            最终返回数量。
        namespace : str
            "chunks" | "knowledge_points" | 其他自定义命名空间。
        filters : dict, optional
            元数据过滤（见 match_filter）。
        mode : str
            "hybrid" | "vector" | "bm25"。单路模式下另一路不触发。
        use_reranker : bool, default False
            True 时在 RRF+过滤之后再跑 cross-encoder 重排；候选池放大到 initial_k，
            以便重排能重新洗牌。reranker 模型不可用 / 推理失败时自动退回原序（见
            reranker.rerank 的兜底）。
        """
        vs = self._vs(namespace)
        total = len(vs.all_chunks())
        if total == 0 or top_k <= 0 or not query.strip():
            return []

        initial_k = max(top_k * INITIAL_MULTIPLIER, top_k)
        vec_hits: list[tuple[int, float]] = []
        bm_hits: list[tuple[int, float]] = []

        if mode in ("hybrid", "vector"):
            vec_hits = self._vector_search(vs, query, initial_k)
        if mode in ("hybrid", "bm25"):
            bm_hits = self._bm25(namespace).search(query, initial_k)

        fused = rrf_merge(vec_hits, bm_hits) if mode == "hybrid" else (
            _single_rank(vec_hits) if mode == "vector" else _single_rank(bm_hits)
        )

        # 候选池：use_reranker 下扩大到 initial_k，让 reranker 有更多牌可洗；
        # 否则维持旧行为（找满 top_k 即止），避免无谓开销。
        candidate_cap = initial_k if use_reranker else top_k

        chunks = vs.all_chunks()
        kept: list[SearchResult] = []
        skipped = 0
        for idx, breakdown in fused:
            if idx < 0 or idx >= len(chunks):
                continue
            ch = chunks[idx]
            if not match_filter(ch.metadata, filters):
                skipped += 1
                continue
            kept.append(SearchResult(
                chunk=ch, score=float(breakdown["rrf"]), score_breakdown=breakdown,
            ))
            if len(kept) >= candidate_cap:
                break

        if use_reranker and kept:
            kept = self._apply_reranker(query, kept, top_k)
        else:
            kept = kept[:top_k]

        if filters and len(kept) < top_k and skipped > len(kept) * _FILTER_WARN_RATIO:
            logger.warning(
                "[hybrid] 过滤后结果不足 top_k（kept=%d, skipped=%d, top_k=%d, filters=%s）",
                len(kept), skipped, top_k, filters,
            )
        return kept

    def _apply_reranker(
        self,
        query: str,
        candidates: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        """用 cross-encoder 重新给 candidates 打分 + 重排，截断 top_k。

        reranker 不可用 / 失败时会返回"原序 score=0.0"——对这种退化情形，保留
        原 RRF 顺序，只把 rerank_score 写成 0，不让调用方误以为重排生效过。
        """
        docs = [r.chunk.text or "" for r in candidates]
        try:
            ordered = _reranker_mod.rerank(query, docs, top_k=len(candidates))
        except Exception as e:  # noqa: BLE001
            logger.warning("[hybrid] reranker 异常，保留 RRF 顺序: %r", e)
            return candidates[:top_k]

        all_zero = bool(ordered) and all(s == 0.0 for _, s in ordered)
        out: list[SearchResult] = []
        if all_zero:
            # 退化路径：维持原顺序，只补 rerank_score=0 作为标记
            for r in candidates[:top_k]:
                r.score_breakdown["rerank_score"] = 0.0
                out.append(r)
            return out

        for idx, score in ordered[:top_k]:
            if idx < 0 or idx >= len(candidates):
                continue
            r = candidates[idx]
            r.score_breakdown["rerank_score"] = float(score)
            r.score = float(score)
            out.append(r)
        return out

    # ---- 向量检索（转成 (idx, score) 形式） ----

    def _vector_search(self, vs: VectorStore, query: str, top_k: int) -> list[tuple[int, float]]:
        raw = vs.search(query, top_k=top_k)
        # raw 是 [(StoredChunk, score)]——需要还原 meta 下标
        chunks = vs.all_chunks()
        id_to_idx = {id(c): i for i, c in enumerate(chunks)}
        out: list[tuple[int, float]] = []
        for c, s in raw:
            i = id_to_idx.get(id(c))
            if i is None:
                # 回退：按 id 字段定位
                for j, cc in enumerate(chunks):
                    if cc.id == c.id:
                        i = j
                        break
            if i is not None:
                out.append((i, float(s)))
        return out


def _single_rank(hits: list[tuple[int, float]]) -> list[tuple[int, dict]]:
    """单路模式下仍走 RRF 公式（只一路贡献），以统一输出形式。"""
    out: list[tuple[int, dict]] = []
    for rank, (idx, s) in enumerate(hits):
        out.append((idx, {
            "vector": float(s) if rank == rank else 0.0,  # 保留原分
            "bm25": 0.0,
            "rrf": 1.0 / (RRF_K + rank + 1),
            "vector_rank": rank,
            "bm25_rank": None,
        }))
    return out
