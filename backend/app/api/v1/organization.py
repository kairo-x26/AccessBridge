"""Organization settings (FR-20): security and automation choices an administrator makes."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import DB, Principal, require
from app.domain import templates as tpl_rules
from app.domain.rbac import Perm
from app.models import Organization
from app.services import audit

router = APIRouter(prefix="/organization", tags=["organization"])
Reader = Annotated[Principal, Depends(require(Perm.REFERRAL_READ))]
Admin = Annotated[Principal, Depends(require(Perm.CONFIG_MANAGE))]

TemplateKey = Literal["schedule_prompt", "appointment_check"]


class OrgOut(BaseModel):
    id: str
    name: str
    slug: str
    require_mfa: bool
    retention_days: int
    preauthorized_reminders: list[str]
    export_min_cell: int


class OrgPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    require_mfa: bool | None = None
    retention_days: int | None = Field(default=None, ge=365, le=3650)
    preauthorized_reminders: list[TemplateKey] | None = None
    export_min_cell: int | None = Field(default=None, ge=0, le=20)


def _out(org: Organization) -> OrgOut:
    cfg = org.configuration or {}
    reminders = (
        cfg.get("preauthorized_templates", [])
        if "send_patient_message" in cfg.get("preauthorized_tools", [])
        else []
    )
    return OrgOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        require_mfa=bool(cfg.get("require_mfa")),
        retention_days=org.retention_days,
        preauthorized_reminders=[r for r in reminders if r in tpl_rules.KEYS],
        export_min_cell=int(cfg.get("export_min_cell", 5)),
    )


@router.get("", response_model=OrgOut)
def get_org(principal: Reader, session: DB) -> OrgOut:
    org = session.get(Organization, principal.organization_id)
    assert org is not None
    return _out(org)


@router.patch("", response_model=OrgOut)
def update_org(body: OrgPatch, principal: Admin, session: DB) -> OrgOut:
    org = session.get(Organization, principal.organization_id)
    assert org is not None
    cfg = dict(org.configuration or {})
    changes = body.model_dump(exclude_none=True)
    if body.name:
        org.name = body.name
    if body.require_mfa is not None:
        cfg["require_mfa"] = body.require_mfa
    if body.retention_days:
        org.retention_days = body.retention_days
    if body.export_min_cell is not None:
        cfg["export_min_cell"] = body.export_min_cell
    if body.preauthorized_reminders is not None:
        # Only low-risk reviewed reminders can be pre-authorized; transmission never can.
        cfg["preauthorized_tools"] = (
            ["send_patient_message"] if body.preauthorized_reminders else []
        )
        cfg["preauthorized_templates"] = sorted(set(body.preauthorized_reminders))
    org.configuration = cfg
    audit.record(
        session,
        organization_id=org.id,
        actor=principal.actor,
        operation="organization.update",
        resource_ref=org.id,
        details={k: str(v) for k, v in changes.items()},
    )
    return _out(org)
