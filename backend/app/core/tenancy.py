"""Tenant isolation helpers (FR-02).

Every tenant-owned query goes through these helpers so the organization filter cannot be
forgotten. A record in another tenant is reported as *not found* so its existence does not
leak across organizations.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound


def scoped[T](model: type[T], organization_id: str) -> Select[T]:
    return select(model).where(model.organization_id == organization_id)  # type: ignore[attr-defined]


def get_scoped[T](session: Session, model: type[T], obj_id: Any, organization_id: str) -> T:
    obj = session.get(model, obj_id)
    if obj is None or obj.organization_id != organization_id:  # type: ignore[attr-defined]
        raise NotFound(f"{model.__name__} not found")
    return obj
