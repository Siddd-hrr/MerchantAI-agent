from __future__ import annotations

import hashlib
import hmac

from services.async_worker.webhook_verifier import verify_razorpay_signature


def test_verify_razorpay_signature_valid() -> None:
    body = b'{"event":"payment.captured","payload":{"payment":{"entity":{"id":"pay_123"}}}}'
    secret = "secret123"
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert verify_razorpay_signature(body=body, signature=signature, secret=secret) is True


def test_verify_razorpay_signature_invalid() -> None:
    body = b'{"event":"payment.captured"}'
    assert verify_razorpay_signature(body=body, signature="bad-signature", secret="secret123") is False


def test_verify_razorpay_signature_missing_secret_or_header() -> None:
    body = b'{"event":"payment.captured"}'
    assert verify_razorpay_signature(body=body, signature="abc", secret="") is False
    assert verify_razorpay_signature(body=body, signature=None, secret="secret123") is False
