from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import select

from app.api.deps import DB, Principal, require
from app.core.errors import ValidationFailed
from app.core.tenancy import get_scoped, scoped
from app.domain.rbac import Perm, Role
from app.models import User
from app.services import audit, auth

router = APIRouter(prefix="/users", tags=["users"])
Manager = Annotated[Principal, Depends(require(Perm.USER_MANAGE))]
Staff = Annotated[Principal, Depends(require(Perm.REFERRAL_READ))]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str
    role: str
    status: str
    mfa_enabled: bool
    last_login_at: datetime | None


class StaffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    full_name: str
    role: str


class InviteIn(BaseModel):
    email: EmailStr
    role: Role


class InviteOut(BaseModel):
    invitation_id: str
    expires_at: datetime
    # Returned so the administrator can deliver it; production would email it instead.
    token: str


class UserPatch(BaseModel):
    role: Role | None = None
    status: Literal["active", "disabled"] | None = None


@router.get("", response_model=list[UserOut])
def list_users(principal: Manager, session: DB) -> list[User]:
    return list(session.scalars(scoped(User, principal.organization_id).order_by(User.full_name)))


@router.get("/staff", response_model=list[StaffOut])
def list_staff(principal: Staff, session: DB) -> list[User]:
    """Assignable colleagues for task ownership, without account details."""
    q = scoped(User, principal.organization_id).where(User.status == "active")
    return list(session.scalars(q.order_by(User.full_name)))


@router.post("/invitations", response_model=InviteOut, status_code=201)
def invite_user(body: InviteIn, principal: Manager, session: DB) -> InviteOut:
    inv, token = auth.invite(
        session,
        organization_id=principal.organization_id,
        email=body.email,
        role=body.role.value,
        invited_by=principal.user_id,
    )
    return InviteOut(invitation_id=inv.id, expires_at=inv.expires_at, token=token)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: str, body: UserPatch, principal: Manager, session: DB) -> User:
    user = get_scoped(session, User, user_id, principal.organization_id)
    if user.id == principal.user_id and (body.role or body.status == "disabled"):
        raise ValidationFailed("You can't change your own role or disable your own account.")
    changes = body.model_dump(exclude_none=True)
    if body.role == Role.ADMIN or user.role == Role.ADMIN:
        admins = session.scalars(
            select(User).where(
                User.organization_id == principal.organization_id,
                User.role == Role.ADMIN,
                User.status == "active",
            )
        ).all()
        removing = body.status == "disabled" or (body.role and body.role != Role.ADMIN)
        if user.role == Role.ADMIN and removing and len(admins) <= 1:
            raise ValidationFailed("Your organization needs at least one active administrator.")
    for k, v in changes.items():
        setattr(user, k, v.value if isinstance(v, Role) else v)
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="user.update",
        resource_ref=user.id,
        details={k: str(v) for k, v in changes.items()},
    )
    return user
