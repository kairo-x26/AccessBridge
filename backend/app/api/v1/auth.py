from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import DB, CurrentPrincipal, mfa_required_for
from app.core.ratelimit import client_ip, limit
from app.core.security import totp_uri
from app.domain.rbac import permissions_for
from app.models import Organization, User
from app.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    organization: str = Field(description="Organization slug")
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"  # noqa: S105
    mfa_required: bool = False
    mfa_challenge: str | None = None


class MfaVerifyIn(BaseModel):
    challenge: str
    code: str = Field(min_length=6, max_length=6)


class MfaCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class AcceptInvitationIn(BaseModel):
    token: str
    full_name: str = Field(min_length=1, max_length=200)
    password: str


class MeOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    organization_id: str
    organization_name: str
    mfa_enabled: bool
    mfa_satisfied: bool
    mfa_required: bool
    preferred_language: str
    permissions: list[str]


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, session: DB, request: Request) -> TokenOut:
    limit(f"login-ip:{client_ip(request)}", limit=30, window_s=300)
    limit(f"login-acct:{body.organization}:{body.email.lower()}", limit=10, window_s=900)
    result = auth.login(
        session, organization_slug=body.organization, email=body.email, password=body.password
    )
    if result.mfa_challenge:
        return TokenOut(mfa_required=True, mfa_challenge=result.mfa_challenge)
    return TokenOut(access_token=result.access_token)


@router.post("/mfa/verify", response_model=TokenOut)
def mfa_verify(body: MfaVerifyIn, session: DB, request: Request) -> TokenOut:
    limit(f"mfa-ip:{client_ip(request)}", limit=20, window_s=300)
    return TokenOut(
        access_token=auth.verify_mfa_challenge(session, challenge=body.challenge, code=body.code)
    )


@router.post("/mfa/setup", response_model=MfaSetupOut)
def mfa_setup(principal: CurrentPrincipal, session: DB) -> MfaSetupOut:
    user = session.get(User, principal.user_id)
    assert user is not None
    secret = auth.begin_mfa_setup(session, user)
    return MfaSetupOut(secret=secret, otpauth_uri=totp_uri(secret, user.email))


@router.post("/mfa/enable", response_model=TokenOut)
def mfa_enable(body: MfaCodeIn, principal: CurrentPrincipal, session: DB) -> TokenOut:
    user = session.get(User, principal.user_id)
    assert user is not None
    return TokenOut(access_token=auth.enable_mfa(session, user, body.code))


@router.post("/accept-invitation", response_model=MeOut, status_code=201)
def accept_invitation(body: AcceptInvitationIn, session: DB, request: Request) -> MeOut:
    limit(f"invite-ip:{client_ip(request)}", limit=10, window_s=3600)
    user = auth.accept_invitation(
        session, token=body.token, full_name=body.full_name, password=body.password
    )
    org = session.get(Organization, user.organization_id)
    assert org is not None
    return _me(user, org, mfa_satisfied=False, mfa_required=False)


@router.get("/me", response_model=MeOut)
def me(principal: CurrentPrincipal, session: DB) -> MeOut:
    user = session.get(User, principal.user_id)
    org = session.get(Organization, principal.organization_id)
    assert user is not None and org is not None
    return _me(
        user, org, mfa_satisfied=principal.mfa, mfa_required=mfa_required_for(session, principal)
    )


def _me(user: User, org: Organization, *, mfa_satisfied: bool, mfa_required: bool) -> MeOut:
    return MeOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        organization_id=org.id,
        organization_name=org.name,
        mfa_enabled=user.mfa_enabled,
        mfa_satisfied=mfa_satisfied,
        mfa_required=mfa_required,
        preferred_language=user.preferred_language,
        permissions=sorted(p.value for p in permissions_for(user.role)),
    )
