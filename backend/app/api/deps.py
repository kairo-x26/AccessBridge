"""Request dependencies: database session, authenticated principal, permission checks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_token
from app.domain.rbac import Perm, has_permission
from app.models import Organization, User

DB = Annotated[Session, Depends(get_session)]


@dataclass(frozen=True)
class Principal:
    user_id: str
    organization_id: str
    role: str
    mfa: bool

    @property
    def actor(self) -> str:
        return f"user:{self.user_id}"


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Sign in to continue.")
    return authorization.split(" ", 1)[1].strip()


def current_principal(
    session: DB, authorization: Annotated[str | None, Header()] = None
) -> Principal:
    claims = decode_token(_bearer(authorization))
    user = session.get(User, claims["sub"])
    # Fail closed: disabled users, moved users and role changes invalidate the token.
    if (
        user is None
        or user.status != "active"
        or user.organization_id != claims["org"]
        or user.role != claims["role"]
    ):
        raise Unauthorized("Session is no longer valid. Sign in again.")
    return Principal(user.id, user.organization_id, user.role, bool(claims.get("mfa")))


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def mfa_required_for(session: Session, principal: Principal) -> bool:
    if get_settings().require_mfa:
        return True
    org = session.get(Organization, principal.organization_id)
    return bool(org and org.configuration.get("require_mfa"))


def require(*perms: Perm) -> Callable[..., Principal]:
    def checker(session: DB, principal: CurrentPrincipal) -> Principal:
        if mfa_required_for(session, principal) and not principal.mfa:
            raise Forbidden(
                "Set up two-step verification to continue.", details={"reason": "mfa_required"}
            )
        missing = [p.value for p in perms if not has_permission(principal.role, p)]
        if missing:
            raise Forbidden("Your role does not allow this action.", details={"missing": missing})
        return principal

    return checker
