"""Sentence-transformers backed embeddings (lazy loaded, cached)."""
from __future__ import annotations

import threading
from typing import Optional

import numpy as np

from backend.config import settings


_model = None
_lock = threading.Lock()


def _load():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer
                _model = SentenceTransformer(settings.embedding_model)
    return _model


def embed(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, 512), dtype="float32")
    model = _load()
    vecs = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return vecs.astype("float32")


def dim() -> int:
    model = _load()
    return int(model.get_sentence_embedding_dimension())
