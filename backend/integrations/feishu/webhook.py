"""飞书事件订阅 webhook 工具：签名校验、challenge 应答、event_id 去重。

纯逻辑层，不依赖任何 HTTP 框架，便于单测。路由层（routes_feishu）调用这些函数。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)


# ============ 签名校验 ============

def verify_signature(
    *,
    timestamp: str,
    nonce: str,
    body: bytes,
    encrypt_key: str,
    received_signature: str,
) -> bool:
    """飞书事件订阅 v2 签名算法：
    signature = sha256(timestamp + nonce + encrypt_key + body)

    encrypt_key 为空时返回 True（开发/mock 场景），生产环境必须配。
    """
    if not encrypt_key:
        logger.warning("[feishu] encrypt_key empty, skipping signature check")
        return True
    if not received_signature:
        return False
    hasher = hashlib.sha256()
    hasher.update(timestamp.encode("utf-8"))
    hasher.update(nonce.encode("utf-8"))
    hasher.update(encrypt_key.encode("utf-8"))
    hasher.update(body)
    expected = hasher.hexdigest()
    return hmac.compare_digest(expected, received_signature)


# ============ Challenge 应答 ============

def build_challenge_response(payload: dict[str, Any]) -> dict[str, Any] | None:
    """飞书首次配置 webhook 会发 url_verification 事件，需原样回 challenge。"""
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}
    return None


# ============ Event ID 去重 ============

class EventDedup:
    """LRU 去重器；飞书会重试同一事件最多 3 次。线程安全。"""

    def __init__(self, *, capacity: int = 2048, ttl_seconds: int = 600):
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()

    def seen(self, event_id: str) -> bool:
        """已见过返回 True；否则记录并返回 False。空 id 视作新事件（不去重）。"""
        if not event_id:
            return False
        now = time.time()
        with self._lock:
            self._evict_expired(now)
            if event_id in self._store:
                self._store.move_to_end(event_id)
                return True
            self._store[event_id] = now
            if len(self._store) > self._capacity:
                self._store.popitem(last=False)
            return False

    def _evict_expired(self, now: float) -> None:
        cutoff = now - self._ttl
        while self._store:
            oldest_id, ts = next(iter(self._store.items()))
            if ts >= cutoff:
                break
            self._store.popitem(last=False)


# 进程级单例
default_dedup = EventDedup()


def extract_event_id(payload: dict[str, Any]) -> str:
    """飞书事件 schema v2: payload.header.event_id"""
    header = payload.get("header") or {}
    return str(header.get("event_id") or "")


# ============ Webhook 完整处理入口 ============

def handle_webhook(
    *,
    raw_body: bytes,
    headers: dict[str, str],
    encrypt_key: str,
    dedup: EventDedup | None = None,
) -> tuple[int, dict[str, Any]]:
    """返回 (http_status, response_body)。

    路由层只需调这一个函数：签名校验失败 → 401；challenge → 直接回 challenge；
    重复事件 → 200 空体（飞书会因此停止重试）；正常事件 → 解析后交给上层路由分发。
    """
    sig = headers.get("X-Lark-Signature", "")
    ts = headers.get("X-Lark-Request-Timestamp", "")
    nonce = headers.get("X-Lark-Request-Nonce", "")
    if not verify_signature(
        timestamp=ts, nonce=nonce, body=raw_body,
        encrypt_key=encrypt_key, received_signature=sig,
    ):
        return 401, {"detail": "invalid signature"}

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return 400, {"detail": "invalid json"}

    challenge = build_challenge_response(payload)
    if challenge is not None:
        return 200, challenge

    d = dedup or default_dedup
    if d.seen(extract_event_id(payload)):
        return 200, {"deduped": True}

    return 200, {"accepted": True, "event": payload}
