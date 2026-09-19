from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet

from shared.config import get_settings

_FIXED_TEST_KEY = base64.urlsafe_b64encode(hashlib.sha256(b"merchant-ai-agent-test-key").digest())


def _is_test_mode() -> bool:
    testing_flag = os.getenv("TESTING", "").strip().lower()
    if testing_flag in {"1", "true", "yes", "on"}:
        return True
    if "PYTEST_CURRENT_TEST" in os.environ:
        return True
    return os.getenv("ENVIRONMENT", "").strip().lower() == "test"


def _resolve_fernet_key() -> bytes:
    settings = get_settings()
    raw_key = settings.credential_encryption_key.strip()
    if not raw_key:
        if _is_test_mode():
            return _FIXED_TEST_KEY
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEY must be configured outside test mode."
        )

    try:
        decoded = base64.urlsafe_b64decode(raw_key.encode("utf-8"))
        if len(decoded) == 32:
            return raw_key.encode("utf-8")
    except Exception:
        pass

    return base64.urlsafe_b64encode(hashlib.sha256(raw_key.encode("utf-8")).digest())


def _get_fernet() -> Fernet:
    return Fernet(_resolve_fernet_key())


def encrypt_secret(value: str) -> str:
    return _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    return _get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
