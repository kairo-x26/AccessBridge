from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import DB, Principal, require
from app.api.v1.schemas import ProviderOut
from app.core.errors import ValidationFailed
from app.core.tenancy import get_scoped, scoped
from app.domain.rbac import Perm
from app.models import ExternalProvider
from app.services import audit
from app.services.referrals import SUPPORTED_SPECIALTIES

router = APIRouter(prefix="/providers", tags=["providers"])
Reader = Annotated[Principal, Depends(require(Perm.REFERRAL_READ))]
Admin = Annotated[Principal, Depends(require(Perm.CONFIG_MANAGE))]


@router.get("", response_model=list[ProviderOut])
def list_providers(
    principal: Reader, session: DB, specialty: str | None = None
) -> list[ExternalProvider]:
    q = scoped(ExternalProvider, principal.organization_id)
    if specialty:
        q = q.where(ExternalProvider.specialty == specialty)
    return list(session.scalars(q.order_by(ExternalProvider.name)))


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    specialty: str
    network_reference: str | None = None
    location: str | None = None
    contact_method: Literal["fhir", "direct", "fax"] = "direct"
    endpoint: str | None = None
    phone: str | None = None
    accepts_referrals: bool = True
    languages: list[str] = []


@router.post("", response_model=ProviderOut, status_code=201)
def create_provider(body: ProviderIn, principal: Admin, session: DB) -> ExternalProvider:
    if body.specialty not in SUPPORTED_SPECIALTIES:
        raise ValidationFailed(f"Unsupported specialty {body.specialty!r}.")
    p = ExternalProvider(organization_id=principal.organization_id, **body.model_dump())
    session.add(p)
    session.flush()
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="provider.create",
        resource_ref=p.id,
    )
    return p


@router.put("/{provider_id}", response_model=ProviderOut)
def update_provider(
    provider_id: str, body: ProviderIn, principal: Admin, session: DB
) -> ExternalProvider:
    p = get_scoped(session, ExternalProvider, provider_id, principal.organization_id)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="provider.update",
        resource_ref=p.id,
    )
    return p
