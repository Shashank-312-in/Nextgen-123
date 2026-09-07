"""Encryption helpers for SMS gateway secrets.

Gateway passwords and device IDs are encrypted at rest with a dedicated
Fernet key. Legacy plaintext values are deliberately NOT decrypted anywhere;
operators must re-enter them once after this hardening is deployed.
"""
from __future__ import annotations

import base64
import binascii
import os

from cryptography.fernet import Fernet

_KEY_ENV_VAR = "SMS_CREDENTIAL_KEY"
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    key = os.environ.get(_KEY_ENV_VAR)
    if not key:
        raise RuntimeError(
            f"{_KEY_ENV_VAR} environment variable is not set. "
            "Refusing to read/write SMS gateway secrets without a real encryption key."
        )
    _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt_secret(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    if is_encrypted_secret(value):
        return value
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    if not is_encrypted_secret(value):
        raise ValueError(
            "Legacy plaintext SMS gateway secret detected. Re-enter the gateway credentials "
            "to complete the security migration."
        )
    return _get_fernet().decrypt(value.encode()).decode()


def is_encrypted_secret(value: str | None) -> bool:
    """Structural Fernet-token check without decrypting the value."""
    if not value:
        return False
    try:
        raw = base64.urlsafe_b64decode(value.encode())
    except (binascii.Error, ValueError, TypeError):
        return False
    return len(raw) >= 57 and raw[0] == 0x80
