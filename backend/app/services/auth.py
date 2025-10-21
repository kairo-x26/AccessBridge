"""Sign-in, MFA enrollment and invitations (FR-01)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import Conflict, Unauthorized, ValidationFailed
from app.core.security import (
    create_access_token,
    create_mfa_challenge_token,
    decode_token,
    hash_password,
    hash_token,
    new_totp_secret,
    password_problems,
    verify_password,
    verify_totp,
)
from app.domain.rbac import Role
from app.models import Invitation, Organization, User
from app.services import audit

MAX_FAILED = 5
LOCK_MINUTES = 15
_GENERIC = "Email or password is incorrect."


@dataclass
class LoginResult:
    access_token: str | None = None
    mfa_challenge: str | None = None


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _token_for(user: User, *, mfa: bool) -> str:
    return create_access_token(
        user_id=user.id, organization_id=user.organization_id, role=user.role, mfa=mfa
    )


def login(session: Session, *, organization_slug: str, email: str, password: str) -> LoginResult:
    org = session.scalar(select(Organization).where(Organization.slug == organization_slug))
    user = (
        session.scalar(
            select(User).where(User.organization_id == org.id, User.email == email.lower())
        )
        if org
        else None
    )
    if user is None:
        verify_password(password, None)  # keep timing similar
        raise Unauthorized(_GENERIC)
    locked = _aware(user.locked_until)
    if locked and locked > utcnow():
        audit.record(
            session,
            organization_id=user.organization_id,
            actor=f"user:{user.id}",
            operation="auth.login",
            outcome="locked",
        )
        session.commit()
        raise Unauthorized("Account is temporarily locked. Try again in 15 minutes.")
    if user.status != "active" or not verify_password(password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED:
            user.locked_until = utcnow() + timedelta(minutes=LOCK_MINUTES)
            user.failed_logins = 0
        audit.record(
            session,
            organization_id=user.organization_id,
            actor=f"user:{user.id}",
            operation="auth.login",
            outcome="denied",
        )
        session.commit()
        raise Unauthorized(_GENERIC)

    user.failed_logins = 0
    user.locked_until = None
    if user.mfa_enabled:
        return LoginResult(mfa_challenge=create_mfa_challenge_token(user.id))
    user.last_login_at = utcnow()
    audit.record(
        session,
        organization_id=user.organization_id,
        actor=f"user:{user.id}",
        operation="auth.login",
    )
    return LoginResult(access_token=_token_for(user, mfa=False))


def verify_mfa_challenge(session: Session, *, challenge: str, code: str) -> str:
    claims = decode_token(challenge, purpose="mfa")
    user = session.get(User, claims["sub"])
    if user is None or user.status != "active" or not user.mfa_secret:
        raise Unauthorized("Sign in again.")
    if not verify_totp(user.mfa_secret, code):
        audit.record(
            session,
            organization_id=user.organization_id,
            actor=f"user:{user.id}",
            operation="auth.mfa",
            outcome="denied",
        )
        session.commit()
        raise Unauthorized("That code didn't match. Enter the current 6-digit code.")
    user.last_login_at = utcnow()
    audit.record(
        session,
        organization_id=user.organization_id,
        actor=f"user:{user.id}",
        operation="auth.login",
        details={"mfa": True},
    )
    return _token_for(user, mfa=True)


def begin_mfa_setup(session: Session, user: User) -> str:
    if user.mfa_enabled:
        raise Conflict("Two-step verification is already on.")
    user.mfa_secret = new_totp_secret()
    return user.mfa_secret


def enable_mfa(session: Session, user: User, code: str) -> str:
    if not user.mfa_secret or not verify_totp(user.mfa_secret, code):
        raise ValidationFailed("That code didn't match. Enter the current 6-digit code.")
    user.mfa_enabled = True
    audit.record(
        session,
        organization_id=user.organization_id,
        actor=f"user:{user.id}",
        operation="auth.mfa_enabled",
        resource_ref=user.id,
    )
    return _token_for(user, mfa=True)


def create_user(
    session: Session,
    *,
    organization_id: str,
    email: str,
    full_name: str,
    role: str,
    password: str,
) -> User:
    if problems := password_problems(password):
        raise ValidationFailed("Password is too weak.", details={"problems": problems})
    user = User(
        organization_id=organization_id,
        email=email.lower(),
        full_name=full_name,
        role=Role(role).value,
        password_hash=hash_password(password),
    )
    session.add(user)
    session.flush()
    return user


def invite(
    session: Session, *, organization_id: str, email: str, role: str, invited_by: str
) -> tuple[Invitation, str]:
    Role(role)
    existing = session.scalar(
        select(User).where(User.organization_id == organization_id, User.email == email.lower())
    )
    if existing:
        raise Conflict("A user with this email already exists in your organization.")
    token = secrets.token_urlsafe(32)
    inv = Invitation(
        organization_id=organization_id,
        email=email.lower(),
        role=role,
        token_hash=hash_token(token),
        invited_by=invited_by,
        expires_at=utcnow() + timedelta(days=7),
    )
    session.add(inv)
    session.flush()
    audit.record(
        session,
        organization_id=organization_id,
        actor=f"user:{invited_by}",
        operation="user.invite",
        resource_ref=inv.id,
        details={"role": role},
    )
    return inv, token


def accept_invitation(session: Session, *, token: str, full_name: str, password: str) -> User:
    inv = session.scalar(select(Invitation).where(Invitation.token_hash == hash_token(token)))
    expires = _aware(inv.expires_at) if inv else None
    if inv is None or inv.accepted_at or (expires and expires < utcnow()):
        raise ValidationFailed("This invitation is invalid or has expired. Ask for a new one.")
    user = create_user(
        session,
        organization_id=inv.organization_id,
        email=inv.email,
        full_name=full_name,
        role=inv.role,
        password=password,
    )
    inv.accepted_at = utcnow()
    audit.record(
        session,
        organization_id=inv.organization_id,
        actor=f"user:{user.id}",
        operation="user.invitation_accepted",
        resource_ref=inv.id,
    )
    return user
