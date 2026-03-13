"""Document intelligence review, validation issues, package approval and checklists."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.deps import DB, Principal, require
from app.core.errors import ValidationFailed
from app.core.tenancy import get_scoped, scoped
from app.domain.checklists import builtin_checklist, validate_items
from app.domain.rbac import Perm
from app.models import (
    ChecklistTemplate,
    ExtractedField,
    Referral,
    ReferralPackage,
    User,
    ValidationIssue,
)
from app.services import audit, package, tasks, validation
from app.services.referrals import SUPPORTED_SPECIALTIES

router = APIRouter(tags=["review"])
Reader = Annotated[Principal, Depends(require(Perm.REFERRAL_READ, Perm.DOCUMENT_READ))]
Editor = Annotated[Principal, Depends(require(Perm.REFERRAL_EDIT))]
Approver = Annotated[Principal, Depends(require(Perm.PACKAGE_APPROVE))]
Configurer = Annotated[Principal, Depends(require(Perm.CONFIG_MANAGE))]


class FieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    name: str
    value: str
    effective_value: str | None
    span_start: int
    span_end: int
    confidence: float
    method: str
    critical: bool
    status: str
    corrected_value: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None


class IssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    item_key: str
    severity: str
    message: str
    status: str
    resolved_by: str | None
    resolution: str | None
    task_id: str | None


class AnalysisOut(BaseModel):
    documents_processed: int
    fields_found: int
    open_blocking: int
    open_warnings: int
    issues: list[str]
    checklist_version: str


@router.post("/referrals/{referral_id}/analyze/sync", response_model=AnalysisOut)
def analyze_now(referral_id: str, principal: Editor, session: DB) -> AnalysisOut:
    """Run extraction and validation inline (used by tests and small manual uploads)."""
    r = get_scoped(session, Referral, referral_id, principal.organization_id)
    s = validation.analyze(session, r, actor=principal.actor)
    return AnalysisOut(**s.__dict__)


@router.get("/referrals/{referral_id}/fields", response_model=list[FieldOut])
def list_fields(referral_id: str, principal: Reader, session: DB) -> list[ExtractedField]:
    get_scoped(session, Referral, referral_id, principal.organization_id)
    return list(
        session.scalars(
            select(ExtractedField)
            .where(ExtractedField.referral_id == referral_id)
            .order_by(ExtractedField.name, ExtractedField.confidence.desc())
        )
    )


class FieldReviewIn(BaseModel):
    action: Literal["accept", "correct", "reject"]
    corrected_value: str | None = Field(default=None, max_length=500)


@router.patch("/fields/{field_id}", response_model=FieldOut)
def review_field(
    field_id: str, body: FieldReviewIn, principal: Editor, session: DB
) -> ExtractedField:
    f = get_scoped(session, ExtractedField, field_id, principal.organization_id)
    referral = get_scoped(session, Referral, f.referral_id, principal.organization_id)
    if referral.status not in ("needs_review", "exception"):
        raise ValidationFailed("Fields can only change while the referral is in review.")
    reviewer = session.get(User, principal.user_id)
    assert reviewer is not None
    package.review_field(
        session, f, reviewer, action=body.action, corrected_value=body.corrected_value
    )
    session.flush()
    validation.sync_issues(session, referral, actor=principal.actor)
    return f


class ValidationOut(BaseModel):
    checklist_version: str
    checklist: list[dict[str, Any]]
    issues: list[IssueOut]
    ready: bool
    blockers: list[str]


@router.get("/referrals/{referral_id}/validation", response_model=ValidationOut)
def get_validation(referral_id: str, principal: Reader, session: DB) -> ValidationOut:
    r = get_scoped(session, Referral, referral_id, principal.organization_id)
    items, version = validation.checklist_for(session, r.organization_id, r.specialty)
    issues = session.scalars(
        select(ValidationIssue)
        .where(ValidationIssue.referral_id == r.id)
        .order_by(ValidationIssue.created_at)
    ).all()
    blockers = package.readiness(session, r)
    return ValidationOut(
        checklist_version=version,
        checklist=[dict(i) for i in items],
        issues=[IssueOut.model_validate(i) for i in issues],
        ready=not blockers,
        blockers=blockers,
    )


class WaiveIn(BaseModel):
    reason: str = Field(min_length=5, max_length=400)


@router.post("/validation-issues/{issue_id}/waive", response_model=IssueOut)
def waive_issue(issue_id: str, body: WaiveIn, principal: Approver, session: DB) -> ValidationIssue:
    issue = get_scoped(session, ValidationIssue, issue_id, principal.organization_id)
    if issue.status != "open":
        raise ValidationFailed("Only open issues can be waived.")
    if issue.item_key.startswith(("identity:", "referral:", "provider:")):
        raise ValidationFailed(
            "Identity, specialty and destination issues can't be waived. "
            "Fix the underlying record instead."
        )
    issue.status = "waived"
    issue.resolved_by = principal.actor
    issue.resolution = body.reason
    if issue.task_id:
        t = session.get(tasks.Task, issue.task_id)
        if t:
            tasks.resolve(session, t, actor=principal.actor, resolution=f"Waived: {body.reason}")
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="validation.waive",
        resource_ref=issue.id,
        details={"item_key": issue.item_key, "referral_id": issue.referral_id},
    )
    return issue


class PackagePreview(BaseModel):
    contents: dict[str, Any]
    ready: bool
    blockers: list[str]
    version: int


class PackageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    referral_id: str
    version: int
    content_hash: str
    approved_by: str
    approved_at: datetime
    note: str | None
    contents: dict[str, Any]


@router.get("/referrals/{referral_id}/package", response_model=PackagePreview)
def preview_package(referral_id: str, principal: Reader, session: DB) -> PackagePreview:
    r = get_scoped(session, Referral, referral_id, principal.organization_id)
    blockers = package.readiness(session, r)
    return PackagePreview(
        contents=package.contents(session, r),
        ready=not blockers,
        blockers=blockers,
        version=r.version,
    )


class ApproveIn(BaseModel):
    expected_version: int
    note: str | None = Field(default=None, max_length=1000)


@router.post("/referrals/{referral_id}/package/approve", response_model=PackageOut, status_code=201)
def approve_package(
    referral_id: str, body: ApproveIn, principal: Approver, session: DB
) -> ReferralPackage:
    r = get_scoped(session, Referral, referral_id, principal.organization_id)
    reviewer = session.get(User, principal.user_id)
    assert reviewer is not None
    pkg = package.approve(
        session, r, reviewer, note=body.note, expected_version=body.expected_version
    )
    # The intake agent takes it from here: it proposes transmission for staff approval.
    from app.agents import orchestrator

    orchestrator.start_run(
        session,
        r,
        workflow="intake",
        trigger=principal.actor,
        idempotency_key=f"after-approval:{pkg.id}",
    )
    return pkg


@router.get("/referrals/{referral_id}/packages", response_model=list[PackageOut])
def list_packages(referral_id: str, principal: Reader, session: DB) -> list[ReferralPackage]:
    get_scoped(session, Referral, referral_id, principal.organization_id)
    return list(
        session.scalars(
            select(ReferralPackage)
            .where(ReferralPackage.referral_id == referral_id)
            .order_by(ReferralPackage.version)
        )
    )


# --- checklists (FR-20) -------------------------------------------------------------


class ChecklistOut(BaseModel):
    specialty: str
    version: str
    items: list[dict[str, Any]]
    customized: bool


@router.get("/checklists", response_model=list[ChecklistOut])
def list_checklists(principal: Reader, session: DB) -> list[ChecklistOut]:
    out = []
    for sp in SUPPORTED_SPECIALTIES:
        items, version = validation.checklist_for(session, principal.organization_id, sp)
        out.append(
            ChecklistOut(
                specialty=sp,
                version=version,
                items=[dict(i) for i in items],
                customized=version != "builtin",
            )
        )
    return out


class ChecklistItemIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    kind: Literal["field", "document", "provider"]
    target: str
    blocking: bool = True


class ChecklistIn(BaseModel):
    items: list[ChecklistItemIn] = Field(min_length=1, max_length=40)


@router.put("/checklists/{specialty}", response_model=ChecklistOut)
def put_checklist(
    specialty: str, body: ChecklistIn, principal: Configurer, session: DB
) -> ChecklistOut:
    if specialty not in SUPPORTED_SPECIALTIES:
        raise ValidationFailed(f"Unsupported specialty {specialty!r}.")
    items = [{**i.model_dump(), "key": f"{i.kind}:{i.target}"} for i in body.items]
    if problems := validate_items(items):
        raise ValidationFailed("Checklist has problems.", details={"problems": problems})
    current = (
        session.scalar(
            select(func.max(ChecklistTemplate.version)).where(
                ChecklistTemplate.organization_id == principal.organization_id,
                ChecklistTemplate.specialty == specialty,
            )
        )
        or 0
    )
    for old in session.scalars(
        scoped(ChecklistTemplate, principal.organization_id).where(
            ChecklistTemplate.specialty == specialty, ChecklistTemplate.active.is_(True)
        )
    ):
        old.active = False
    tpl = ChecklistTemplate(
        organization_id=principal.organization_id,
        specialty=specialty,
        version=current + 1,
        items=items,
        updated_by=principal.actor,
    )
    session.add(tpl)
    session.flush()
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="checklist.update",
        resource_ref=tpl.id,
        details={"specialty": specialty, "version": tpl.version},
    )
    return ChecklistOut(
        specialty=specialty, version=f"v{tpl.version}", items=items, customized=True
    )


@router.delete("/checklists/{specialty}", response_model=ChecklistOut)
def reset_checklist(specialty: str, principal: Configurer, session: DB) -> ChecklistOut:
    for old in session.scalars(
        scoped(ChecklistTemplate, principal.organization_id).where(
            ChecklistTemplate.specialty == specialty, ChecklistTemplate.active.is_(True)
        )
    ):
        old.active = False
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="checklist.reset",
        details={"specialty": specialty},
    )
    return ChecklistOut(
        specialty=specialty,
        version="builtin",
        items=[dict(i) for i in builtin_checklist(specialty)],
        customized=False,
    )
