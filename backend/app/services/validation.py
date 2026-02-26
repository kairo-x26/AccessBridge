"""Document analysis and checklist validation (FR-05, FR-06).

Missing information becomes an open issue and a coordinator task. Nothing here invents a
value: a field is present only if a grounded candidate or a person supplied it.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.checklists import CRITICAL_FIELDS, ChecklistItem, builtin_checklist
from app.models import (
    ChecklistTemplate,
    ExtractedField,
    Referral,
    ReferralDocument,
    Task,
    ValidationIssue,
)
from app.services import audit, document_ai, storage, tasks
from app.services.referrals import SUPPORTED_SPECIALTIES

log = logging.getLogger(__name__)
# Optional extra extractor (e.g. model-assisted); its output is grounded like any other.
Assist = Callable[[str], list[document_ai.Candidate]]


@dataclass
class AnalysisSummary:
    documents_processed: int = 0
    fields_found: int = 0
    open_blocking: int = 0
    open_warnings: int = 0
    issues: list[str] = field(default_factory=list)
    checklist_version: str = "builtin"


def checklist_for(
    session: Session, organization_id: str, specialty: str
) -> tuple[list[ChecklistItem], str]:
    tpl = session.scalar(
        select(ChecklistTemplate)
        .where(
            ChecklistTemplate.organization_id == organization_id,
            ChecklistTemplate.specialty == specialty,
            ChecklistTemplate.active.is_(True),
        )
        .order_by(ChecklistTemplate.version.desc())
    )
    if tpl:
        return [ChecklistItem(**i) for i in tpl.items], f"v{tpl.version}"  # type: ignore[typeddict-item]
    return builtin_checklist(specialty), "builtin"


def process_document(
    session: Session,
    doc: ReferralDocument,
    *,
    actor: str,
    assist: Assist | None = None,
) -> int:
    """Extract text, classify and store grounded candidates. Returns fields stored."""
    data = storage.get(doc.storage_uri, doc.organization_id)
    text, status = document_ai.extract_text(data, doc.content_type)
    doc.extraction_status = status
    if text is None:
        doc.doc_type, doc.doc_type_confidence = "other", None
        return 0
    doc.text_content = text
    doc.doc_type, doc.doc_type_confidence = document_ai.classify(text, doc.filename)
    candidates = document_ai.extract_fields(text)
    if assist is not None:
        candidates += assist(text)
    stored = 0
    seen: set[tuple[str, int, int]] = set()
    for c in candidates:
        if not document_ai.grounded(text, c):
            log.warning(
                "discarded ungrounded candidate",
                extra={"fields": {"field": c.name, "method": c.method, "document_id": doc.id}},
            )
            continue
        if (c.name, c.start, c.end) in seen:
            continue
        seen.add((c.name, c.start, c.end))
        session.add(
            ExtractedField(
                organization_id=doc.organization_id,
                referral_id=doc.referral_id,
                document_id=doc.id,
                name=c.name,
                value=c.value,
                span_start=c.start,
                span_end=c.end,
                confidence=c.confidence,
                method=c.method,
                critical=c.name in CRITICAL_FIELDS,
                extraction_version=document_ai.EXTRACTOR_VERSION,
            )
        )
        stored += 1
    session.flush()
    audit.record(
        session,
        organization_id=doc.organization_id,
        actor=actor,
        operation="document.analyze",
        resource_ref=doc.id,
        details={"doc_type": doc.doc_type, "status": status, "fields": stored},
    )
    return stored


def _best_by_name(fields: list[ExtractedField]) -> dict[str, list[ExtractedField]]:
    grouped: dict[str, list[ExtractedField]] = defaultdict(list)
    for f in fields:
        if f.status != "rejected":
            grouped[f.name].append(f)
    for name in grouped:
        grouped[name].sort(
            key=lambda f: (f.status in ("accepted", "corrected"), f.confidence), reverse=True
        )
    return grouped


def evaluate(session: Session, referral: Referral) -> list[tuple[str, str, str]]:
    """Return the current problems as (item_key, severity, message). Pure read."""
    problems: list[tuple[str, str, str]] = []
    if referral.specialty not in SUPPORTED_SPECIALTIES:
        problems.append(
            (
                "referral:specialty",
                "blocking",
                "Specialty isn't supported. Choose a supported specialty.",
            )
        )
    items, _ = checklist_for(session, referral.organization_id, referral.specialty)
    fields = list(
        session.scalars(select(ExtractedField).where(ExtractedField.referral_id == referral.id))
    )
    docs = list(
        session.scalars(select(ReferralDocument).where(ReferralDocument.referral_id == referral.id))
    )
    by_name = _best_by_name(fields)
    doc_types = {d.doc_type for d in docs}

    for item in items:
        sev = "blocking" if item["blocking"] else "warning"
        if item["kind"] == "field":
            if not by_name.get(item["target"]):
                problems.append((item["key"], sev, f"{item['label']} is missing."))
        elif item["kind"] == "document":
            if item["target"] not in doc_types:
                problems.append((item["key"], sev, f"{item['label']} is missing."))
        elif item["kind"] == "provider":
            if referral.provider is None:
                problems.append((item["key"], sev, "Choose a destination specialist."))
            elif not referral.provider.accepts_referrals:
                problems.append(
                    (item["key"], sev, f"{referral.provider.name} isn't accepting referrals.")
                )

    # Conflicting values across documents (reviewed values win over candidates).
    for name, cands in by_name.items():
        top = cands[0]
        if top.status in ("accepted", "corrected"):
            continue
        values = {
            document_ai.normalize(name, c.effective_value or "")
            for c in cands
            if c.confidence >= 0.6
        }
        if len(values) > 1:
            sev = "blocking" if name in CRITICAL_FIELDS else "warning"
            problems.append(
                (
                    f"conflict:{name}",
                    sev,
                    f"Documents disagree on {name.replace('_', ' ')}. Confirm the correct value.",
                )
            )
        elif top.confidence < 0.6:
            problems.append(
                (
                    f"low_confidence:{name}",
                    "warning",
                    f"{name.replace('_', ' ').capitalize()} looks malformed. Check it.",
                )
            )

    # Identity cross-check against the patient record: fail closed on mismatch.
    patient = referral.patient
    for name, expected in (
        ("birth_date", patient.birth_date),
        ("patient_name", patient.display_name),
    ):
        found = by_name.get(name)
        if not found or not expected:
            continue
        cands = found
        val = cands[0].effective_value or ""
        got, want = document_ai.normalize(name, val), document_ai.normalize(name, expected)
        if name == "patient_name":
            got_parts, want_parts = set(got.replace(",", " ").split()), set(want.split())
            mismatch = not want_parts.issubset(got_parts)
        else:
            mismatch = got != want
        if mismatch:
            problems.append(
                (
                    f"identity:{name}",
                    "blocking",
                    f"Document {name.replace('_', ' ')} doesn't match the patient "
                    "record. Confirm identity before continuing.",
                )
            )

    for d in docs:
        if d.extraction_status in ("needs_ocr", "failed"):
            problems.append(
                (
                    f"document_unreadable:{d.id}",
                    "warning",
                    f"{d.filename} couldn't be read automatically. Review it by hand.",
                )
            )
    return problems


def sync_issues(session: Session, referral: Referral, *, actor: str) -> AnalysisSummary:
    problems = evaluate(session, referral)
    current = {key: (sev, msg) for key, sev, msg in problems}
    existing = {
        i.item_key: i
        for i in session.scalars(
            select(ValidationIssue).where(
                ValidationIssue.referral_id == referral.id,
                ValidationIssue.status.in_(("open", "waived")),
            )
        )
    }
    for key, issue in existing.items():
        if key not in current and issue.status == "open":
            issue.status = "resolved"
            issue.resolved_by = actor
            issue.resolution = "No longer applies"
            if issue.task_id:
                t = session.get(Task, issue.task_id)
                if t:
                    tasks.resolve(session, t, actor=actor, resolution="Information received")
    for key, (sev, msg) in current.items():
        prior = existing.get(key)
        if prior:
            prior.severity, prior.message = sev, msg
            continue
        issue = ValidationIssue(
            organization_id=referral.organization_id,
            referral_id=referral.id,
            item_key=key,
            severity=sev,
            message=msg,
        )
        session.add(issue)
        session.flush()
        if sev == "blocking":
            kind = "exception" if key.startswith("identity:") else "missing_info"
            task, _ = tasks.ensure_task(
                session,
                organization_id=referral.organization_id,
                referral_id=referral.id,
                kind=kind,
                title=msg,
                owner_id=referral.owner_id,
                created_by=actor,
                priority="high" if kind == "exception" else "normal",
                dedupe_key=f"issue:{referral.id}:{key}",
            )
            issue.task_id = task.id
    session.flush()
    _, version = checklist_for(session, referral.organization_id, referral.specialty)
    open_rows = [
        p for p in problems if existing.get(p[0]) is None or existing[p[0]].status == "open"
    ]
    return AnalysisSummary(
        open_blocking=sum(1 for p in open_rows if p[1] == "blocking"),
        open_warnings=sum(1 for p in open_rows if p[1] == "warning"),
        issues=[p[0] for p in open_rows],
        checklist_version=version,
    )


def analyze(
    session: Session,
    referral: Referral,
    *,
    actor: str,
    assist: Assist | None = None,
) -> AnalysisSummary:
    processed = found = 0
    for doc in session.scalars(
        select(ReferralDocument).where(
            ReferralDocument.referral_id == referral.id,
            ReferralDocument.extraction_status == "pending",
        )
    ):
        found += process_document(session, doc, actor=actor, assist=assist)
        processed += 1
    summary = sync_issues(session, referral, actor=actor)
    summary.documents_processed, summary.fields_found = processed, found
    audit.record(
        session,
        organization_id=referral.organization_id,
        actor=actor,
        operation="referral.analyze",
        resource_ref=referral.id,
        details={"documents": processed, "fields": found, "blocking": summary.open_blocking},
    )
    return summary
