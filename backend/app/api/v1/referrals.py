from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Header, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import DB, Principal, require
from app.api.idempotency import body_hash, run_idempotent
from app.api.v1.schemas import (
    DocumentOut,
    Page,
    PatientOut,
    ProviderOut,
    ReferralDetail,
    ReferralSummary,
    StatusEventOut,
    TaskOut,
    TransitionOption,
)
from app.core.errors import NotFound, ValidationFailed
from app.core.tenancy import get_scoped, scoped
from app.domain.rbac import Perm, has_permission
from app.domain.state_machine import (
    ACCEPTED_EVIDENCE,
    REASON_REQUIRED,
    Status,
    allowed_targets,
)
from app.integrations import fhir
from app.models import (
    ExternalProvider,
    PatientReference,
    Referral,
    ReferralDocument,
    ReferralStatusEvent,
    Task,
    User,
)
from app.services import audit, intake, referrals, storage
from app.services.referrals import DocumentIn, IntakeRecord, PatientIn
from app.services.tasks import OPEN_STATES

router = APIRouter(prefix="/referrals", tags=["referrals"])
Reader = Annotated[Principal, Depends(require(Perm.REFERRAL_READ))]
Importer = Annotated[Principal, Depends(require(Perm.REFERRAL_IMPORT))]
Editor = Annotated[Principal, Depends(require(Perm.REFERRAL_EDIT))]
Mover = Annotated[Principal, Depends(require(Perm.REFERRAL_TRANSITION))]
Uploader = Annotated[Principal, Depends(require(Perm.DOCUMENT_UPLOAD))]

MAX_UPLOAD = 10 * 1024 * 1024
ALLOWED_TYPES = {"application/pdf", "text/plain", "image/png", "image/jpeg", "text/csv"}


# --- presenters -------------------------------------------------------------------


def _open_task_counts(session: Session, ids: list[str]) -> dict[str, int]:
    if not ids:
        return {}
    rows = session.execute(
        select(Task.referral_id, func.count())
        .where(Task.referral_id.in_(ids), Task.status.in_(OPEN_STATES))
        .group_by(Task.referral_id)
    ).all()
    return {r: n for r, n in rows if r}


def _owner_names(session: Session, ids: set[str | None]) -> dict[str, str]:
    clean = [i for i in ids if i]
    if not clean:
        return {}
    return {u.id: u.full_name for u in session.scalars(select(User).where(User.id.in_(clean)))}


def summarize(r: Referral, open_tasks: int, owner_name: str | None) -> ReferralSummary:
    return ReferralSummary(
        id=r.id,
        status=r.status,
        progress_status=r.progress_status,
        specialty=r.specialty,
        priority_from_source=r.priority_from_source,
        patient_name=r.patient.display_name,
        patient_ehr_id=r.patient.ehr_patient_id,
        provider_name=r.provider.name if r.provider else None,
        owner_id=r.owner_id,
        owner_name=owner_name,
        source_system=r.source_system,
        source_id=r.source_id,
        age_days=referrals.age_days(r),
        open_tasks=open_tasks,
        created_at=r.created_at,
        status_changed_at=r.status_changed_at,
        appointment_at=r.appointment_at,
        version=r.version,
    )


def patient_view(p: PatientReference, role: str) -> PatientOut:
    out = PatientOut(
        id=p.id,
        ehr_patient_id=p.ehr_patient_id,
        display_name=p.display_name,
        preferred_language=p.preferred_language,
        preferred_channel=p.preferred_channel,
        contact_verified=p.contact_verified,
        opted_out=p.opted_out_at is not None,
        needs_interpreter=p.needs_interpreter,
        transportation_need=p.transportation_need,
    )
    if has_permission(role, Perm.MESSAGE_READ):
        out.birth_date, out.phone, out.email = p.birth_date, p.phone, p.email
    return out


def next_options(status: Status) -> list[TransitionOption]:
    return [
        TransitionOption(
            status=t.value,
            accepted_evidence=sorted(e.value for e in ev) if (ev := ACCEPTED_EVIDENCE[t]) else None,
            reason_required=t in REASON_REQUIRED,
        )
        for t in sorted(allowed_targets(status), key=lambda s: list(Status).index(s))
    ]


def build_detail(session: Session, r: Referral, principal: Principal) -> ReferralDetail:
    counts = _open_task_counts(session, [r.id])
    names = _owner_names(session, {r.owner_id})
    base = summarize(r, counts.get(r.id, 0), names.get(r.owner_id or ""))
    docs = session.scalars(
        select(ReferralDocument)
        .where(ReferralDocument.referral_id == r.id)
        .order_by(ReferralDocument.created_at)
    ).all()
    events = session.scalars(
        select(ReferralStatusEvent)
        .where(ReferralStatusEvent.referral_id == r.id)
        .order_by(ReferralStatusEvent.timestamp)
    ).all()
    task_rows = session.scalars(
        select(Task).where(Task.referral_id == r.id).order_by(Task.created_at.desc())
    ).all()
    can_move = has_permission(principal.role, Perm.REFERRAL_TRANSITION)
    return ReferralDetail(
        **base.model_dump(),
        reason_from_source=r.reason_from_source,
        referring_clinician=r.referring_clinician,
        exception_reason=r.exception_reason,
        legal_hold=r.legal_hold,
        purged_at=r.purged_at,
        package_approved_by=r.package_approved_by,
        package_approved_at=r.package_approved_at,
        patient=patient_view(r.patient, principal.role),
        provider=ProviderOut.model_validate(r.provider) if r.provider else None,
        documents=[DocumentOut.model_validate(d) for d in docs],
        events=[StatusEventOut.model_validate(e) for e in events],
        tasks=[TaskOut.model_validate(t) for t in task_rows]
        if has_permission(principal.role, Perm.TASK_READ)
        else [],
        next_statuses=next_options(Status(r.status)) if can_move else [],
    )


# --- intake -----------------------------------------------------------------------


class ImportResult(BaseModel):
    imported: list[str] = []
    duplicates: list[str] = []
    exceptions: list[str] = []
    errors: list[dict[str, str]] = []


def _ingest_all(
    session: Session,
    principal: Principal,
    records: list[IntakeRecord],
    errors: list[dict[str, str]],
) -> ImportResult:
    result = ImportResult(errors=errors)
    for rec in records:
        res = referrals.ingest(session, principal.organization_id, rec, actor=principal.actor)
        (result.duplicates if res.duplicate else result.imported).append(res.referral.id)
        if res.identity_conflict:
            result.exceptions.append(res.referral.id)
    return result


class FhirImportIn(BaseModel):
    bundle: dict[str, Any]


@router.post("/import", response_model=ImportResult, status_code=201)
def import_fhir(
    body: FhirImportIn,
    principal: Importer,
    session: DB,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Ingest an authorized FHIR R4 bundle containing ServiceRequests (spec §9)."""

    def compute() -> ImportResult:
        try:
            parsed = fhir.parse_bundle(body.bundle)
        except fhir.FhirParseError as exc:
            raise ValidationFailed(str(exc)) from exc
        return _ingest_all(session, principal, parsed.records, parsed.errors)

    return run_idempotent(
        session,
        organization_id=principal.organization_id,
        key=idempotency_key,
        endpoint="referrals.import",
        request_hash=body_hash(body.bundle),
        status_code=201,
        compute=compute,
    )


@router.post("/import/csv", response_model=ImportResult, status_code=201)
async def import_csv(
    principal: Importer, session: DB, file: UploadFile = File(...)
) -> ImportResult:
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise ValidationFailed("File is larger than 10 MB.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationFailed("File must be UTF-8 encoded CSV.") from exc
    parsed = intake.parse_csv(text)
    return _ingest_all(session, principal, parsed.records, parsed.errors)


class ManualReferralIn(BaseModel):
    ehr_patient_id: str = Field(min_length=1, max_length=80)
    given_name: str = Field(min_length=1, max_length=100)
    family_name: str = Field(min_length=1, max_length=100)
    birth_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    phone: str | None = None
    email: str | None = None
    preferred_language: str = "en"
    specialty: str
    priority_from_source: Literal["routine", "urgent", "asap", "stat"] = "routine"
    reason_from_source: str | None = None
    referring_clinician: str | None = None
    provider_id: str | None = None
    source_id: str | None = Field(default=None, description="Paper/fax reference if any")


@router.post("", response_model=ReferralDetail, status_code=201)
def create_manual(body: ManualReferralIn, principal: Importer, session: DB) -> ReferralDetail:
    """Manual intake (workflow A alternative flow)."""
    from app.core.db import new_id

    if body.specialty not in referrals.SUPPORTED_SPECIALTIES:
        raise ValidationFailed(
            f"Unsupported specialty {body.specialty!r}.",
            details={"supported": list(referrals.SUPPORTED_SPECIALTIES)},
        )
    provider = None
    if body.provider_id:
        provider = get_scoped(
            session, ExternalProvider, body.provider_id, principal.organization_id
        )
    rec = IntakeRecord(
        source_system="manual",
        source_id=body.source_id or new_id("man"),
        patient=PatientIn(
            ehr_patient_id=body.ehr_patient_id,
            given_name=body.given_name,
            family_name=body.family_name,
            birth_date=body.birth_date,
            phone=body.phone,
            email=body.email,
            preferred_language=body.preferred_language,
        ),
        specialty=body.specialty,
        priority_from_source=body.priority_from_source,
        reason_from_source=body.reason_from_source,
        referring_clinician=body.referring_clinician,
        provider_name=provider.name if provider else None,
        provider_reference=provider.network_reference if provider else None,
    )
    res = referrals.ingest(session, principal.organization_id, rec, actor=principal.actor)
    if res.duplicate:
        raise ValidationFailed(
            "A referral with this source reference already exists.",
            details={"referral_id": res.referral.id},
        )
    if provider:
        res.referral.provider_id = provider.id
    return build_detail(session, res.referral, principal)


# --- queries ----------------------------------------------------------------------

SORTS = {
    "oldest": Referral.created_at.asc(),
    "newest": Referral.created_at.desc(),
    "status_changed": Referral.status_changed_at.asc(),
}


@router.get("", response_model=Page[ReferralSummary])
def list_referrals(
    principal: Reader,
    session: DB,
    status: Annotated[list[str] | None, Query()] = None,
    specialty: str | None = None,
    owner_id: str | None = None,
    unassigned: bool = False,
    q: str | None = Query(None, max_length=100),
    created_before: datetime | None = None,
    sort: Literal["oldest", "newest", "status_changed"] = "oldest",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> Page[ReferralSummary]:
    stmt = scoped(Referral, principal.organization_id).join(Referral.patient)
    if status:
        valid = {s.value for s in Status}
        bad = [s for s in status if s not in valid]
        if bad:
            raise ValidationFailed(f"Unknown status: {', '.join(bad)}")
        stmt = stmt.where(Referral.status.in_(status))
    if specialty:
        stmt = stmt.where(Referral.specialty == specialty)
    if owner_id == "me":
        owner_id = principal.user_id
    if owner_id:
        stmt = stmt.where(Referral.owner_id == owner_id)
    if unassigned:
        stmt = stmt.where(Referral.owner_id.is_(None))
    if created_before:
        stmt = stmt.where(Referral.created_at < created_before)
    if q:
        # Every word must match something, so "rosa delgado" finds Rosa Delgado.
        for word in q.lower().split()[:5]:
            like = f"%{word}%"
            stmt = stmt.where(
                or_(
                    func.lower(PatientReference.family_name).like(like),
                    func.lower(PatientReference.given_name).like(like),
                    func.lower(PatientReference.ehr_patient_id).like(like),
                    func.lower(Referral.id).like(like),
                    func.lower(Referral.source_id).like(like),
                )
            )
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        session.scalars(
            stmt.order_by(SORTS[sort]).offset((page - 1) * page_size).limit(page_size)
        ).unique()
    )
    counts = _open_task_counts(session, [r.id for r in rows])
    names = _owner_names(session, {r.owner_id for r in rows})
    return Page[ReferralSummary](
        items=[summarize(r, counts.get(r.id, 0), names.get(r.owner_id or "")) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{referral_id}", response_model=ReferralDetail)
def get_referral(referral_id: str, principal: Reader, session: DB) -> ReferralDetail:
    r = get_scoped(session, Referral, referral_id, principal.organization_id)
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="referral.view",
        resource_ref=r.id,
    )
    return build_detail(session, r, principal)


class ReferralPatch(BaseModel):
    expected_version: int
    owner_id: str | None = None
    provider_id: str | None = None
    specialty: str | None = None
    clear_owner: bool = False


@router.patch("/{referral_id}", response_model=ReferralDetail)
def update_referral(
    referral_id: str, body: ReferralPatch, principal: Editor, session: DB
) -> ReferralDetail:
    from app.core.errors import Conflict

    r = get_scoped(session, Referral, referral_id, principal.organization_id)
    if body.expected_version != r.version:
        raise Conflict(
            "This referral changed since you loaded it. Refresh and try again.",
            details={"current_version": r.version},
        )
    changes: dict[str, str | None] = {}
    if body.owner_id:
        owner = get_scoped(session, User, body.owner_id, principal.organization_id)
        r.owner_id = owner.id
        changes["owner_id"] = owner.id
    elif body.clear_owner:
        r.owner_id = None
        changes["owner_id"] = None
    if body.provider_id:
        provider = get_scoped(
            session, ExternalProvider, body.provider_id, principal.organization_id
        )
        if not provider.accepts_referrals:
            raise ValidationFailed(f"{provider.name} is not accepting referrals.")
        r.provider_id = provider.id
        changes["provider_id"] = provider.id
    if body.specialty:
        if body.specialty not in referrals.SUPPORTED_SPECIALTIES:
            raise ValidationFailed(f"Unsupported specialty {body.specialty!r}.")
        if Status(r.status) not in (Status.NEEDS_REVIEW, Status.EXCEPTION):
            raise ValidationFailed("Specialty can only change while the referral is in review.")
        r.specialty = body.specialty
        changes["specialty"] = body.specialty
    if changes:
        r.version += 1
        audit.record(
            session,
            organization_id=principal.organization_id,
            actor=principal.actor,
            operation="referral.update",
            resource_ref=r.id,
            details=changes,
        )
    session.flush()
    session.refresh(r)
    return build_detail(session, r, principal)


class StatusEventIn(BaseModel):
    to_status: Status
    evidence_type: str | None = None
    evidence_reference: str | None = Field(default=None, max_length=300)
    reason: str | None = Field(default=None, max_length=500)
    correction: bool = False
    expected_version: int | None = None


@router.post("/{referral_id}/status-events", response_model=StatusEventOut, status_code=201)
def record_status_event(
    referral_id: str,
    body: StatusEventIn,
    principal: Mover,
    session: DB,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Record an evidence-backed state transition (spec §9)."""
    r = get_scoped(session, Referral, referral_id, principal.organization_id)
    if body.correction and principal.role != "admin":
        from app.core.errors import Forbidden

        raise Forbidden("Only administrators can correct a closed referral.")
    if body.to_status == Status.READY:
        raise ValidationFailed("Approve the referral package to mark it ready.")

    def compute() -> StatusEventOut:
        ev = referrals.transition(
            session,
            r,
            body.to_status,
            actor=principal.actor,
            evidence_type=body.evidence_type,
            evidence_reference=body.evidence_reference,
            reason=body.reason,
            correction=body.correction,
            expected_version=body.expected_version,
        )
        return StatusEventOut.model_validate(ev)

    return run_idempotent(
        session,
        organization_id=principal.organization_id,
        key=idempotency_key,
        endpoint=f"referrals.status:{referral_id}",
        request_hash=body_hash(body.model_dump()),
        status_code=201,
        compute=compute,
    )


@router.get("/{referral_id}/events", response_model=list[StatusEventOut])
def list_events(referral_id: str, principal: Reader, session: DB) -> list[ReferralStatusEvent]:
    get_scoped(session, Referral, referral_id, principal.organization_id)
    return list(
        session.scalars(
            select(ReferralStatusEvent)
            .where(ReferralStatusEvent.referral_id == referral_id)
            .order_by(ReferralStatusEvent.timestamp)
        )
    )


# --- documents --------------------------------------------------------------------


@router.post("/{referral_id}/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    referral_id: str, principal: Uploader, session: DB, file: UploadFile = File(...)
) -> ReferralDocument:
    r = get_scoped(session, Referral, referral_id, principal.organization_id)
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise ValidationFailed("File is larger than 10 MB.")
    if not data:
        raise ValidationFailed("File is empty.")
    ctype = (file.content_type or "").split(";")[0]
    if ctype not in ALLOWED_TYPES:
        raise ValidationFailed(
            "Upload a PDF, text, PNG or JPEG file.", details={"content_type": ctype}
        )
    doc, created = referrals.add_document(
        session,
        r,
        DocumentIn(file.filename or "upload", ctype, data),
        actor=principal.actor,
        source_system="upload",
    )
    if created and r.status in ("submitted", "acknowledged", "scheduled"):
        # Specialist paperwork arriving later in the journey: let the completion agent look.
        from app.agents import orchestrator

        orchestrator.start_run(
            session,
            r,
            workflow="completion",
            trigger=principal.actor,
            idempotency_key=f"document:{doc.id}",
        )
    return doc


docs_router = APIRouter(prefix="/documents", tags=["documents"])
DocReader = Annotated[Principal, Depends(require(Perm.DOCUMENT_READ))]


@docs_router.get("/{document_id}/content")
def document_content(document_id: str, principal: DocReader, session: DB) -> Response:
    doc = get_scoped(session, ReferralDocument, document_id, principal.organization_id)
    try:
        data = storage.get(doc.storage_uri, principal.organization_id)
    except (FileNotFoundError, PermissionError) as exc:
        raise NotFound("Document content is unavailable.") from exc
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="document.read",
        resource_ref=doc.id,
    )
    return Response(
        data,
        media_type=doc.content_type,
        headers={
            "content-disposition": f'inline; filename="{doc.id}"',
            "cache-control": "no-store",
            "x-content-type-options": "nosniff",
        },
    )


@docs_router.get("/{document_id}/text")
def document_text(document_id: str, principal: DocReader, session: DB) -> dict[str, Any]:
    doc = get_scoped(session, ReferralDocument, document_id, principal.organization_id)
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="document.read_text",
        resource_ref=doc.id,
    )
    return {"id": doc.id, "text": doc.text_content, "extraction_status": doc.extraction_status}


class LegalHoldIn(BaseModel):
    hold: bool
    reason: str = Field(min_length=5, max_length=300)


@router.post("/{referral_id}/legal-hold", response_model=ReferralDetail)
def set_legal_hold(
    referral_id: str,
    body: LegalHoldIn,
    principal: Annotated[Principal, Depends(require(Perm.CONFIG_MANAGE))],
    session: DB,
) -> ReferralDetail:
    """Place or lift a legal hold; held referrals are never purged by retention."""
    r = get_scoped(session, Referral, referral_id, principal.organization_id)
    if r.purged_at:
        raise ValidationFailed("This referral's working data was already purged.")
    r.legal_hold = body.hold
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="referral.legal_hold",
        resource_ref=r.id,
        details={"hold": body.hold, "reason": body.reason},
    )
    return build_detail(session, r, principal)
