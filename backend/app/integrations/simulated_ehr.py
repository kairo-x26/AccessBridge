"""Simulated EHR producing synthetic FHIR R4 referral bundles and specialist Task updates.

All people, identifiers and clinical text here are fictional. Used by tests, the seed
script and the demo in place of a live EHR connection (spec §20 first milestone).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SyntheticPatient:
    mrn: str
    given: str
    family: str
    birth_date: str
    phone: str | None = None
    email: str | None = None
    language: str = "en"


@dataclass
class SyntheticReferral:
    id: str
    patient: SyntheticPatient
    specialty_text: str
    reason: str
    priority: str = "routine"
    requester: str = "Dr. Amara Okafor"
    performer: str | None = None
    performer_ref: str | None = None
    documents: list[tuple[str, str, bytes]] = field(default_factory=list)


def referral_letter(
    p: SyntheticPatient,
    *,
    specialty: str,
    reason: str,
    insurance: str | None = "Medicaid — Plan ID MCD-448812",
    member_id: str | None = "MBR-55120934",
    clinician: str = "Dr. Amara Okafor",
    npi: str | None = "1457382913",
    include_diagnosis: bool = True,
    extra: str = "",
) -> bytes:
    lines = [
        "RIVERBEND COMMUNITY HEALTH — SPECIALTY REFERRAL",
        "",
        f"Patient Name: {p.given} {p.family}",
        f"Date of Birth: {p.birth_date}",
        f"MRN: {p.mrn}",
    ]
    if p.phone:
        lines.append(f"Phone: {p.phone}")
    if insurance:
        lines.append(f"Insurance: {insurance}")
    if member_id:
        lines.append(f"Member ID: {member_id}")
    lines += [
        f"Referring Provider: {clinician}",
    ]
    if npi:
        lines.append(f"Referring NPI: {npi}")
    lines += [
        f"Specialty Requested: {specialty}",
        f"Reason for Referral: {reason}",
    ]
    if include_diagnosis:
        lines.append("Diagnosis Code: I10")
    if extra:
        lines += ["", extra]
    lines += ["", "Signed electronically."]
    return "\n".join(lines).encode()


def bundle(*referrals: SyntheticReferral) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    seen_patients: set[str] = set()
    for r in referrals:
        p = r.patient
        if p.mrn not in seen_patients:
            seen_patients.add(p.mrn)
            telecom = []
            if p.phone:
                telecom.append({"system": "phone", "value": p.phone})
            if p.email:
                telecom.append({"system": "email", "value": p.email})
            entries.append(
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": f"pt-{p.mrn}",
                        "identifier": [{"system": "urn:riverbend:mrn", "value": p.mrn}],
                        "name": [{"family": p.family, "given": p.given.split()}],
                        "birthDate": p.birth_date,
                        "telecom": telecom,
                        "communication": [{"language": {"coding": [{"code": p.language}]}}],
                    }
                }
            )
        supporting = []
        for i, (title, ctype, data) in enumerate(r.documents):
            did = f"{r.id}-doc{i}"
            supporting.append({"reference": f"DocumentReference/{did}"})
            entries.append(
                {
                    "resource": {
                        "resourceType": "DocumentReference",
                        "id": did,
                        "status": "current",
                        "content": [
                            {
                                "attachment": {
                                    "contentType": ctype,
                                    "title": title,
                                    "data": base64.b64encode(data).decode(),
                                }
                            }
                        ],
                    }
                }
            )
        performer: dict[str, Any] | None = None
        if r.performer:
            performer = {"display": r.performer}
            if r.performer_ref:
                performer["identifier"] = {"value": r.performer_ref}
        sr: dict[str, Any] = {
            "resourceType": "ServiceRequest",
            "id": r.id,
            "status": "active",
            "intent": "order",
            "priority": r.priority,
            "code": {"text": r.specialty_text},
            "subject": {"reference": f"Patient/pt-{p.mrn}"},
            "requester": {"display": r.requester},
            "reasonCode": [{"text": r.reason}],
            "supportingInfo": supporting,
        }
        if performer:
            sr["performer"] = [performer]
        entries.append({"resource": sr})
    return {"resourceType": "Bundle", "type": "collection", "entry": entries}


def task_update(
    service_request_id: str,
    status: str,
    *,
    version: int = 1,
    task_id: str | None = None,
    business_status: str | None = None,
    appointment: str | None = None,
    report_reference: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    res: dict[str, Any] = {
        "resourceType": "Task",
        "id": task_id or f"task-{service_request_id}",
        "meta": {"versionId": str(version)},
        "status": status,
        "intent": "order",
        "focus": {"reference": f"ServiceRequest/{service_request_id}"},
    }
    if business_status:
        res["businessStatus"] = {"text": business_status}
    outputs = []
    if appointment:
        outputs.append({"type": {"text": "appointment"}, "valueDateTime": appointment})
    if report_reference:
        outputs.append(
            {"type": {"text": "consult-note"}, "valueReference": {"reference": report_reference}}
        )
    if outputs:
        res["output"] = outputs
    if note:
        res["note"] = [{"text": note}]
    return res


ROSA = SyntheticPatient("100234", "Rosa", "Delgado", "1968-03-14", "+1 555 010 2231", language="es")
JAMES = SyntheticPatient("100871", "James", "Whitfield", "1955-11-02", "+1 555 010 7781")
MEI = SyntheticPatient(
    "101552", "Mei", "Tanaka", "1990-07-21", "+1 555 010 4410", email="mei.tanaka@example.org"
)
