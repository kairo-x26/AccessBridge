"""Encrypted document storage. Local filesystem stand-in for encrypted object storage (S3+KMS)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.core.config import get_settings
from app.core.crypto import decrypt_bytes, encrypt_bytes


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _root() -> Path:
    return Path(get_settings().storage_dir)


def put(organization_id: str, data: bytes) -> tuple[str, str]:
    """Store bytes; returns ``(storage_uri, sha256)``. Content-addressed, so re-puts are no-ops."""
    digest = checksum(data)
    rel = Path(organization_id) / digest[:2] / f"{digest}.bin"
    path = _root() / rel
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(encrypt_bytes(data))
        tmp.replace(path)
    return f"local://{rel.as_posix()}", digest


def get(storage_uri: str, organization_id: str) -> bytes:
    rel = storage_uri.removeprefix("local://")
    if not rel.startswith(f"{organization_id}/") or ".." in rel:
        raise PermissionError("document is outside the organization's storage")
    data = decrypt_bytes((_root() / rel).read_bytes())
    if checksum(data) != rel.rsplit("/", 1)[-1].removesuffix(".bin"):
        raise ValueError("document checksum mismatch")
    return data


def delete(storage_uri: str, organization_id: str) -> bool:
    rel = storage_uri.removeprefix("local://")
    if not rel.startswith(f"{organization_id}/") or ".." in rel:
        raise PermissionError("document is outside the organization's storage")
    path = _root() / rel
    if path.exists():
        path.unlink()
        return True
    return False
