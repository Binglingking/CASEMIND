"""飞书 webhook 签名 / challenge / 去重测试。"""
from __future__ import annotations

import hashlib
import json

from backend.integrations.feishu.webhook import (
    EventDedup,
    handle_webhook,
    verify_signature,
)


KEY = "test_key_123"


def _sign(timestamp: str, nonce: str, body: bytes) -> str:
    h = hashlib.sha256()
    h.update(timestamp.encode("utf-8"))
    h.update(nonce.encode("utf-8"))
    h.update(KEY.encode("utf-8"))
    h.update(body)
    return h.hexdigest()


def test_verify_signature_ok():
    body = b'{"a":1}'
    sig = _sign("100", "n", body)
    assert verify_signature(
        timestamp="100", nonce="n", body=body,
        encrypt_key=KEY, received_signature=sig,
    )


def test_verify_signature_mismatch():
    body = b'{"a":1}'
    assert not verify_signature(
        timestamp="100", nonce="n", body=body,
        encrypt_key=KEY, received_signature="wrong",
    )


def test_verify_signature_skipped_when_key_empty():
    # 空 key（开发模式）→ 直接放行
    assert verify_signature(
        timestamp="100", nonce="n", body=b"",
        encrypt_key="", received_signature="anything",
    )


def test_dedup_first_seen_is_false_second_is_true():
    d = EventDedup()
    assert d.seen("evt1") is False
    assert d.seen("evt1") is True
    assert d.seen("evt2") is False


def test_dedup_empty_id_never_dedups():
    d = EventDedup()
    assert d.seen("") is False
    assert d.seen("") is False


def test_handle_webhook_challenge():
    body = json.dumps({"type": "url_verification", "challenge": "xyz"}).encode("utf-8")
    sig = _sign("1", "n", body)
    status, resp = handle_webhook(
        raw_body=body,
        headers={
            "X-Lark-Signature": sig,
            "X-Lark-Request-Timestamp": "1",
            "X-Lark-Request-Nonce": "n",
        },
        encrypt_key=KEY,
    )
    assert status == 200
    assert resp == {"challenge": "xyz"}


def test_handle_webhook_bad_signature():
    body = b'{"any":"thing"}'
    status, resp = handle_webhook(
        raw_body=body,
        headers={
            "X-Lark-Signature": "bad",
            "X-Lark-Request-Timestamp": "1",
            "X-Lark-Request-Nonce": "n",
        },
        encrypt_key=KEY,
    )
    assert status == 401


def test_handle_webhook_dedup_returns_deduped_flag():
    body = json.dumps({
        "header": {"event_id": "e1", "event_type": "im.message.receive_v1"},
        "event": {"x": 1},
    }).encode("utf-8")
    sig = _sign("1", "n", body)
    dedup = EventDedup()
    h = {
        "X-Lark-Signature": sig,
        "X-Lark-Request-Timestamp": "1",
        "X-Lark-Request-Nonce": "n",
    }
    s1, r1 = handle_webhook(raw_body=body, headers=h, encrypt_key=KEY, dedup=dedup)
    s2, r2 = handle_webhook(raw_body=body, headers=h, encrypt_key=KEY, dedup=dedup)
    assert s1 == 200 and r1.get("accepted") is True
    assert s2 == 200 and r2.get("deduped") is True
