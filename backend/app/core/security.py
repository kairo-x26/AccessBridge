"""Password hashing, TOTP (RFC 6238) and JWT access tokens. Standard library + PyJWT only."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import jwt

from app.core.config import get_settings
from app.core.errors import Unauthorized

# --- Passwords (scrypt, N=2^14, r=8, p=1) -----------------------------------------

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    _, salt_b64, digest_b64 = stored.split("$")
    digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < 12:
        problems.append("Use at least 12 characters.")
    if password.lower() == password or password.upper() == password:
        problems.append("Mix upper- and lower-case letters.")
    if not any(c.isdigit() for c in password):
        problems.append("Include a number.")
    return problems


# --- TOTP ---------------------------------------------------------------------------


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret: str, counter: int, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF) % 10**digits
    return str(code).zfill(digits)


def totp_now(secret: str, at: float | None = None, step: int = 30) -> str:
    return _hotp(secret, int((at or time.time()) // step))


def verify_totp(secret: str, code: str, at: float | None = None, window: int = 1) -> bool:
    if not code or not code.isdigit():
        return False
    counter = int((at or time.time()) // 30)
    return any(
        hmac.compare_digest(_hotp(secret, counter + d), code) for d in range(-window, window + 1)
    )


def totp_uri(secret: str, account: str) -> str:
    issuer = get_settings().mfa_issuer
    return (
        f"otpauth://totp/{quote(issuer)}:{quote(account)}"
        f"?secret={secret}&issuer={quote(issuer)}&digits=6&period=30"
    )


# --- Tokens -------------------------------------------------------------------------


def create_access_token(
    *, user_id: str, organization_id: str, role: str, mfa: bool, minutes: int | None = None
) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    claims = {
        "sub": user_id,
        "org": organization_id,
        "role": role,
        "mfa": mfa,
        "iss": s.jwt_issuer,
        "iat": now,
        "exp": now + timedelta(minutes=minutes or s.access_token_minutes),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(claims, s.jwt_secret, algorithm="HS256")


def create_mfa_challenge_token(user_id: str) -> str:
    """Short-lived token proving the password step passed; only redeemable with a TOTP code."""
    s = get_settings()
    now = datetime.now(UTC)
    claims = {
        "sub": user_id,
        "purpose": "mfa",
        "iss": s.jwt_issuer,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    return jwt.encode(claims, s.jwt_secret, algorithm="HS256")


def decode_token(token: str, *, purpose: str | None = None) -> dict[str, Any]:
    s = get_settings()
    try:
        claims = jwt.decode(token, s.jwt_secret, algorithms=["HS256"], issuer=s.jwt_issuer)
    except jwt.PyJWTError as exc:
        raise Unauthorized("Session is invalid or expired. Sign in again.") from exc
    if claims.get("purpose") != purpose:
        raise Unauthorized("Token cannot be used for this request.")
    return claims


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
