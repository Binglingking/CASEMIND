"""Cross-encoder 重排器（bge-reranker-base）。

设计约束：
  - 懒加载：默认不在 import 时触发模型下载；只有 `rerank()` 被首次调用才加载
  - 单例 + 锁：与 embeddings.py 相同的多线程保护
  - 失败软降级：任何加载/推理异常都返回"原序"（配合上层告警），绝不抛到业务层
  - 无副作用：本模块只读配置、加载模型、打分；不写盘

接口契约：
  rerank(query, docs, top_k=None) -> list[(original_index, score)]
    - 结果按 score 降序
    - top_k 截断；None 表示返回全部
    - docs 为空 / query 为空字符串时直接返回 []
    - 任意异常 → 返回 [(i, 0.0) for i in range(len(docs))][:top_k]（原序兜底）
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from backend.config import settings


logger = logging.getLogger(__name__)


_model = None
_load_failed = False          # 一次失败就不再重试，避免每次检索都卡住加载
_lock = threading.Lock()


def _load():
    """返回 CrossEncoder 实例；若不可用返回 None。"""
    global _model, _load_failed
    if _load_failed:
        return None
    if _model is not None:
        return _model
    with _lock:
        if _load_failed:
            return None
        if _model is not None:
            return _model
        try:
            from sentence_transformers import CrossEncoder
            _model = CrossEncoder(settings.reranker_model)
            logger.info("[reranker] 已加载模型 %s", settings.reranker_model)
        except Exception as e:  # noqa: BLE001
            _load_failed = True
            logger.warning("[reranker] 模型加载失败，降级为原序: %r", e)
            return None
    return _model


def is_available() -> bool:
    """仅用于诊断/测试——不会触发懒加载。"""
    return _model is not None and not _load_failed


def _reset_for_tests() -> None:
    """测试专用：清掉缓存的模型句柄与失败标记。"""
    global _model, _load_failed
    _model = None
    _load_failed = False


def rerank(
    query: str,
    docs: list[str],
    top_k: Optional[int] = None,
) -> list[tuple[int, float]]:
    """Cross-encoder 重排。

    Parameters
    ----------
    query : str
        查询文本；空字符串直接返回 []
    docs : list[str]
        候选文档文本；与返回值里的 index 一一对应
    top_k : int, optional
        截断数量；None 返回全部

    Returns
    -------
    list[tuple[int, float]]
        [(original_index, score), ...]，按 score 降序。模型不可用时退化为原序，score=0.0。
    """
    if not query or not docs:
        return []

    cap = len(docs) if top_k is None else max(0, min(top_k, len(docs)))
    if cap == 0:
        return []

    model = _load()
    if model is None:
        return [(i, 0.0) for i in range(cap)]

    try:
        pairs = [(query, d or "") for d in docs]
        scores = model.predict(pairs, show_progress_bar=False)
        # scores 可能是 np.ndarray 或 list[float]
        ordered = sorted(
            ((i, float(s)) for i, s in enumerate(scores)),
            key=lambda kv: kv[1],
            reverse=True,
        )
        return ordered[:cap]
    except Exception as e:  # noqa: BLE001
        logger.warning("[reranker] 推理失败，降级为原序: %r", e)
        return [(i, 0.0) for i in range(cap)]
