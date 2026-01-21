"""Specialty document checklists (FR-06, FR-20).

These are administrative completeness rules, not clinical criteria. Organizations can override
a specialty's checklist; the built-in set is the fallback and the starting template.
"""

from __future__ import annotations

from typing import Literal, TypedDict

DOC_TYPES = (
    "referral_form",
    "insurance_card",
    "clinical_note",
    "lab_result",
    "imaging_report",
    "consult_note",
    "consent_form",
    "other",
)

FIELDS = {
    "patient_name": "Patient name",
    "birth_date": "Date of birth",
    "mrn": "Medical record number",
    "phone": "Patient phone",
    "insurance_payer": "Insurance payer",
    "member_id": "Insurance member ID",
    "referring_provider": "Referring clinician",
    "referring_npi": "Referring clinician NPI",
    "specialty_requested": "Specialty requested",
    "reason_for_referral": "Reason for referral",
    "diagnosis_code": "Diagnosis code",
}
# Fields a person must confirm before a package can be approved (spec §11: critical fields).
CRITICAL_FIELDS = frozenset({"patient_name", "birth_date", "member_id", "insurance_payer"})


class ChecklistItem(TypedDict):
    key: str
    label: str
    kind: Literal["field", "document", "provider"]
    target: str  # field name, document type, or "destination"
    blocking: bool


def _f(name: str, blocking: bool = True) -> ChecklistItem:
    return {
        "key": f"field:{name}",
        "label": FIELDS[name],
        "kind": "field",
        "target": name,
        "blocking": blocking,
    }


def _d(doc_type: str, label: str, blocking: bool = True) -> ChecklistItem:
    return {
        "key": f"document:{doc_type}",
        "label": label,
        "kind": "document",
        "target": doc_type,
        "blocking": blocking,
    }


BASE: list[ChecklistItem] = [
    _f("patient_name"),
    _f("birth_date"),
    _f("insurance_payer"),
    _f("member_id"),
    _f("referring_provider"),
    _f("referring_npi", blocking=False),
    _f("reason_for_referral"),
    _f("diagnosis_code", blocking=False),
    _d("referral_form", "Signed referral form"),
    {
        "key": "provider:destination",
        "label": "Destination specialist accepting referrals",
        "kind": "provider",
        "target": "destination",
        "blocking": True,
    },
]

EXTRA: dict[str, list[ChecklistItem]] = {
    "cardiology": [_d("clinical_note", "Recent visit note")],
    "dermatology": [_d("clinical_note", "Visit note or lesion description", blocking=False)],
    "endocrinology": [_d("lab_result", "Recent lab results")],
    "gastroenterology": [_d("clinical_note", "Recent visit note")],
    "neurology": [
        _d("clinical_note", "Recent visit note"),
        _d("imaging_report", "Imaging report, if done", blocking=False),
    ],
    "orthopedics": [_d("imaging_report", "X-ray or imaging report")],
    "ophthalmology": [],
    "behavioral_health": [_d("consent_form", "Signed consent to share records")],
}


def builtin_checklist(specialty: str) -> list[ChecklistItem]:
    return [*BASE, *EXTRA.get(specialty, [])]


def validate_items(items: list[dict]) -> list[str]:
    """Problems with an administrator-supplied checklist; empty when valid."""
    problems = []
    keys = set()
    for i, item in enumerate(items):
        kind, target = item.get("kind"), item.get("target")
        if kind == "field" and target not in FIELDS:
            problems.append(f"Item {i + 1}: unknown field {target!r}.")
        elif kind == "document" and target not in DOC_TYPES:
            problems.append(f"Item {i + 1}: unknown document type {target!r}.")
        elif kind == "provider" and target != "destination":
            problems.append(f"Item {i + 1}: provider items must target 'destination'.")
        elif kind not in ("field", "document", "provider"):
            problems.append(f"Item {i + 1}: kind must be field, document or provider.")
        if not str(item.get("label") or "").strip():
            problems.append(f"Item {i + 1}: needs a label.")
        key = f"{kind}:{target}"
        if key in keys:
            problems.append(f"Item {i + 1}: duplicate of an earlier item.")
        keys.add(key)
    return problems
