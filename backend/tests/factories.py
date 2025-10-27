"""Test helpers for building tenants and signed-in users."""

from __future__ import annotations

from dataclasses import dataclass

from app.core import db
from app.core.security import create_access_token
from app.models import Organization
from app.services import auth

PASSWORD = "Correct-Horse-42"


@dataclass
class Actor:
    user_id: str
    organization_id: str
    role: str
    email: str

    def token(self, mfa: bool = True) -> str:
        return create_access_token(
            user_id=self.user_id, organization_id=self.organization_id, role=self.role, mfa=mfa
        )

    def headers(self, mfa: bool = True) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(mfa)}"}


def make_org(slug: str = "riverbend", name: str = "Riverbend Community Health") -> str:
    with db.session_factory()() as s:
        org = Organization(name=name, slug=slug)
        s.add(org)
        s.commit()
        return org.id


def make_user(org_id: str, role: str, email: str | None = None) -> Actor:
    email = email or f"{role}.{org_id[-8:]}@example.org"
    with db.session_factory()() as s:
        u = auth.create_user(
            s,
            organization_id=org_id,
            email=email,
            full_name=f"Test {role}",
            role=role,
            password=PASSWORD,
        )
        s.commit()
        return Actor(u.id, org_id, role, email)
