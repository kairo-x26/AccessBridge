"""Field-level encryption for sensitive attributes (spec §8: encrypt and minimize).

Uses Fernet (AES-128-CBC + HMAC-SHA256). The key comes from ``AB_FIELD_ENCRYPTION_KEY``;
development derives a stable key from the JWT secret so local data survives restarts.
Deployments should source the key from a managed KMS-backed secret.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, TypeDecorator

from app.core.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    s = get_settings()
    key = s.field_encryption_key
    if not key:
        key = base64.urlsafe_b64encode(hashlib.sha256(s.jwt_secret.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt_bytes(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    return _fernet().decrypt(token)


class EncryptedString(TypeDecorator[str]):
    """A string column stored encrypted at rest."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: object) -> str | None:
        if value is None:
            return None
        return _fernet().encrypt(value.encode()).decode()

    def process_result_value(self, value: str | None, dialect: object) -> str | None:
        if value is None:
            return None
        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            return None
