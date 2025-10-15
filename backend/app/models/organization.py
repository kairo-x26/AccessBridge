from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("org"))
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Days to retain closed referral working data; legal holds override (spec §8 lifecycle).
    retention_days: Mapped[int] = mapped_column(default=2555)
