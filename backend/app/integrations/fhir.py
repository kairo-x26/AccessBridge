"""FHIR R4 adapter: parse ServiceRequest bundles into intake records and Task updates into
proposed state changes.

The parser is defensive: inbound resources are untrusted, every field is optional until
proven otherwise, and anything the platform can't interpret is reported, not guessed.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.state_machine import Status
from app.services.referrals import DocumentIn, IntakeRecord, PatientIn

SOURCE_SYSTEM = "fhir"
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

_SPECIALTY_KEYWORDS = {
    "cardio": "cardiology",
    "heart": "cardiology",
    "derm": "dermatology",
    "skin": "dermatology",
    "endocrin": "endocrinology",
    "diabet": "endocrinology",
    "gastro": "gastroenterology",
    "gi ": "gastroenterology",
    "neuro": "neurology",
    "ortho": "orthopedics",
    "ophthal": "ophthalmology",
    "eye": "ophthalmology",
    "retina": "ophthalmology",
    "behavioral": "behavioral_health",
    "psych": "behavioral_health",
    "mental": "behavioral_health",
}
_PRIORITIES = {"routine", "urgent", "asap", "stat"}


class FhirParseError(ValueError):
    pass


@dataclass
class BundleParse:
    records: list[IntakeRecord] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)


def normalize_specialty(text: str | None) -> str:
    if not text:
        return "unspecified"
    t = f" {text.lower()} "
    for key, value in _SPECIALTY_KEYWORDS.items():
        if key in t:
            return value
    return "unsupported"


def _text_of(concept: Any) -> str | None:
    if not isinstance(concept, dict):
        return None
    if concept.get("text"):
        return str(concept["text"])
    for coding in concept.get("coding") or []:
        if isinstance(coding, dict) and coding.get("display"):
            return str(coding["display"])
    return None


def _ref_id(ref: Any, kind: str) -> str | None:
    if isinstance(ref, dict) and isinstance(ref.get("reference"), str):
        r = ref["reference"]
        if r.startswith(f"{kind}/"):
            return r.split("/", 1)[1]
        if r.startswith("#"):
            return r[1:]
    return None


def _patient(resource: dict[str, Any]) -> PatientIn:
    pid = None
    for ident in resource.get("identifier") or []:
        if isinstance(ident, dict) and ident.get("value"):
            pid = str(ident["value"])
            break
    pid = pid or resource.get("id")
    names = resource.get("name") or []
    if not pid or not names or not isinstance(names[0], dict):
        raise FhirParseError("Patient needs an identifier and a name")
    name = names[0]
    given = " ".join(name.get("given") or []).strip()
    family = str(name.get("family") or "").strip()
    if not given or not family:
        raise FhirParseError("Patient name needs given and family parts")
    phone = email = None
    for tel in resource.get("telecom") or []:
        if not isinstance(tel, dict):
            continue
        if tel.get("system") == "phone" and not phone:
            phone = tel.get("value")
        elif tel.get("system") == "email" and not email:
            email = tel.get("value")
    language = "en"
    for comm in resource.get("communication") or []:
        code = None
        for coding in (comm.get("language") or {}).get("coding") or []:
            code = coding.get("code")
        if code:
            language = str(code).split("-")[0].lower()
            break
    return PatientIn(
        ehr_patient_id=str(pid),
        given_name=given,
        family_name=family,
        birth_date=resource.get("birthDate"),
        phone=phone,
        email=email,
        preferred_language=language,
    )


def _document(resource: dict[str, Any]) -> DocumentIn | None:
    for content in resource.get("content") or []:
        att = content.get("attachment") if isinstance(content, dict) else None
        if not isinstance(att, dict) or not att.get("data"):
            continue
        try:
            data = base64.b64decode(att["data"], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise FhirParseError("DocumentReference attachment is not valid base64") from exc
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise FhirParseError("DocumentReference attachment exceeds 10 MB")
        title = att.get("title") or resource.get("description") or f"{resource.get('id')}.txt"
        return DocumentIn(
            filename=str(title),
            content_type=str(att.get("contentType") or "application/octet-stream"),
            data=data,
        )
    return None


def parse_bundle(bundle: dict[str, Any]) -> BundleParse:
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise FhirParseError("Expected a FHIR Bundle")
    by_ref: dict[tuple[str, str], dict[str, Any]] = {}
    requests = []
    for entry in bundle.get("entry") or []:
        res = entry.get("resource") if isinstance(entry, dict) else None
        if not isinstance(res, dict) or "resourceType" not in res:
            continue
        rid = str(res.get("id") or "")
        by_ref[(res["resourceType"], rid)] = res
        if res["resourceType"] == "ServiceRequest":
            requests.append(res)

    out = BundleParse()
    for sr in requests:
        sr_id = str(sr.get("id") or "")
        try:
            if not sr_id:
                raise FhirParseError("ServiceRequest needs an id")
            if sr.get("intent") not in (None, "order", "original-order", "plan", "proposal"):
                raise FhirParseError(f"Unsupported intent {sr.get('intent')!r}")
            if sr.get("status") not in (None, "active", "draft"):
                raise FhirParseError(f"ServiceRequest status {sr.get('status')!r} is not active")
            pid = _ref_id(sr.get("subject"), "Patient")
            patient_res = by_ref.get(("Patient", pid or ""))
            if not patient_res:
                raise FhirParseError("ServiceRequest subject Patient is missing from the bundle")
            patient = _patient(patient_res)
            specialty_text = _text_of(sr.get("code")) or next(
                (t for c in sr.get("category") or [] if (t := _text_of(c))), None
            )
            performer = (sr.get("performer") or [None])[0]
            provider_ref = None
            provider_name = None
            if isinstance(performer, dict):
                provider_name = performer.get("display")
                ident = performer.get("identifier")
                if isinstance(ident, dict):
                    provider_ref = ident.get("value")
            requester = sr.get("requester")
            priority = str(sr.get("priority") or "routine").lower()
            docs = []
            for info in sr.get("supportingInfo") or []:
                did = _ref_id(info, "DocumentReference")
                if did and (doc_res := by_ref.get(("DocumentReference", did))):
                    doc = _document(doc_res)
                    if doc:
                        docs.append(doc)
            reason = next((t for c in sr.get("reasonCode") or [] if (t := _text_of(c))), None)
            out.records.append(
                IntakeRecord(
                    source_system=SOURCE_SYSTEM,
                    source_id=sr_id,
                    patient=patient,
                    specialty=normalize_specialty(specialty_text),
                    priority_from_source=priority if priority in _PRIORITIES else "routine",
                    reason_from_source=reason,
                    referring_clinician=requester.get("display")
                    if isinstance(requester, dict)
                    else None,
                    provider_name=provider_name,
                    provider_reference=provider_ref,
                    documents=docs,
                )
            )
        except FhirParseError as exc:
            out.errors.append({"source_id": sr_id or "(missing)", "error": str(exc)})
    if not requests:
        out.errors.append({"source_id": "(bundle)", "error": "Bundle has no ServiceRequest"})
    return out


# --- Task updates (reconciliation input) ---------------------------------------------

_TASK_STATUS_MAP: dict[str, Status] = {
    "received": Status.ACKNOWLEDGED,
    "accepted": Status.ACKNOWLEDGED,
    "in-progress": Status.ACKNOWLEDGED,
    "completed": Status.COMPLETED,
    "rejected": Status.DECLINED,
    "cancelled": Status.CANCELLED,
    "failed": Status.EXCEPTION,
}


@dataclass
class TaskUpdate:
    external_id: str  # Task/<id>/_history/<version>
    task_id: str
    source_request_id: str
    fhir_status: str
    proposed_status: Status | None
    appointment_at: datetime | None
    completion_reference: str | None
    note: str | None


def parse_task(resource: dict[str, Any]) -> TaskUpdate:
    if not isinstance(resource, dict) or resource.get("resourceType") != "Task":
        raise FhirParseError("Expected a FHIR Task")
    task_id = str(resource.get("id") or "")
    focus = _ref_id(resource.get("focus"), "ServiceRequest") or _ref_id(
        (resource.get("basedOn") or [None])[0], "ServiceRequest"
    )
    if not task_id or not focus:
        raise FhirParseError("Task needs an id and a ServiceRequest focus")
    status = str(resource.get("status") or "")
    version = str(
        (resource.get("meta") or {}).get("versionId")
        or (resource.get("meta") or {}).get("lastUpdated")
        or "1"
    )
    business = (_text_of(resource.get("businessStatus")) or "").lower()
    appointment_at = None
    completion_ref = None
    for out in resource.get("output") or []:
        if not isinstance(out, dict):
            continue
        if out.get("valueDateTime"):
            try:
                appointment_at = datetime.fromisoformat(str(out["valueDateTime"]))
            except ValueError as exc:
                raise FhirParseError("Task output valueDateTime is not ISO 8601") from exc
        ref = out.get("valueReference")
        if isinstance(ref, dict) and ref.get("reference"):
            completion_ref = str(ref["reference"])
    proposed = _TASK_STATUS_MAP.get(status)
    if status in ("in-progress", "accepted") and ("schedul" in business or appointment_at):
        proposed = Status.SCHEDULED
    note = None
    for n in resource.get("note") or []:
        if isinstance(n, dict) and n.get("text"):
            note = str(n["text"])[:300]
    return TaskUpdate(
        external_id=f"Task/{task_id}/_history/{version}",
        task_id=task_id,
        source_request_id=focus,
        fhir_status=status,
        proposed_status=proposed,
        appointment_at=appointment_at,
        completion_reference=completion_ref,
        note=note,
    )


def service_request_task(referral_source_id: str, status: str, *, task_id: str) -> dict[str, Any]:
    """Build an outbound FHIR Task reflecting local workflow status (where writes are supported)."""
    return {
        "resourceType": "Task",
        "id": task_id,
        "status": status,
        "intent": "order",
        "focus": {"reference": f"ServiceRequest/{referral_source_id}"},
    }
