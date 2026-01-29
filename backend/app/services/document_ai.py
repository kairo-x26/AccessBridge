"""Document intelligence (FR-05): text extraction, classification and evidence-linked fields.

Every candidate value carries the exact character span it came from. :func:`grounded` is the
"never fabricate" gate: a value whose span does not reproduce it verbatim is discarded,
whatever produced it (pattern or model).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date

from app.domain.checklists import DOC_TYPES

EXTRACTOR_VERSION = "patterns-2026.01"


@dataclass(frozen=True)
class Candidate:
    name: str
    value: str
    start: int
    end: int
    confidence: float
    method: str = "pattern"


# --- text -------------------------------------------------------------------------


def extract_text(data: bytes, content_type: str) -> tuple[str | None, str]:
    """Return ``(text, status)`` where status is done | needs_ocr | failed."""
    if content_type in ("text/plain", "text/csv"):
        for enc in ("utf-8", "latin-1"):
            try:
                return data.decode(enc), "done"
            except UnicodeDecodeError:
                continue
        return None, "failed"
    if content_type == "application/pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:  # noqa: BLE001 - any parser failure means "a person must look"
            return None, "failed"
        return (text, "done") if text.strip() else (None, "needs_ocr")
    if content_type.startswith("image/"):
        # OCR is a deployment add-on; scanned images go to a person until it is configured.
        return None, "needs_ocr"
    return None, "failed"


# --- classification ---------------------------------------------------------------

_DOC_SIGNALS: dict[str, list[tuple[str, float]]] = {
    "referral_form": [
        (r"\breferral\b", 2),
        (r"reason for referral", 3),
        (r"specialty requested", 3),
        (r"refer(?:red|ring) (?:to|provider|physician)", 2),
    ],
    "insurance_card": [
        (r"member id", 3),
        (r"\bgroup\s*(?:#|no|number)", 2),
        (r"\bpayer\b", 2),
        (r"\bsubscriber\b", 2),
        (r"\bcopay\b", 2),
        (r"insurance card", 3),
    ],
    "clinical_note": [
        (r"\bassessment\b", 2),
        (r"\bplan\b", 1),
        (r"history of present illness", 3),
        (r"\bvitals?\b", 2),
        (r"progress note|visit note|office visit", 3),
    ],
    "lab_result": [
        (r"\breference range\b", 3),
        (r"\bresult\b", 1),
        (r"\bspecimen\b", 2),
        (r"\ba1c\b|\bhemoglobin\b|\bglucose\b|\blipid", 2),
        (r"\blab(?:oratory)?\b", 1),
    ],
    "imaging_report": [
        (r"\bimpression\b", 2),
        (r"\bx-?ray\b|\bmri\b|\bct\b|\bultrasound\b", 3),
        (r"\bradiolog", 2),
        (r"\bfindings\b", 1),
    ],
    "consult_note": [
        (r"\bconsult(?:ation)? (?:note|report)\b", 4),
        (r"\bthank you for (?:the|this) referral\b", 4),
        (r"\brecommendations?\b", 1),
        (r"\bseen in (?:clinic|consult)", 2),
    ],
    "consent_form": [
        (r"\bconsent\b", 3),
        (r"\bauthoriz(?:e|ation) (?:to )?(?:release|disclose|share)", 3),
        (r"\bsignature\b", 1),
    ],
}


def classify(text: str, filename: str = "") -> tuple[str, float]:
    haystack = f"{filename}\n{text[:20000]}".lower()
    scores = {
        kind: sum(w for pat, w in signals if re.search(pat, haystack))
        for kind, signals in _DOC_SIGNALS.items()
    }
    best = max(scores, key=lambda k: scores[k])
    total = sum(scores.values())
    if scores[best] < 3:
        return "other", 0.5
    confidence = round(min(0.99, 0.55 + 0.45 * scores[best] / max(total, 1)), 2)
    assert best in DOC_TYPES
    return best, confidence


# --- fields -----------------------------------------------------------------------

# (field, label regex, confidence when the label is specific)
_LABELS: list[tuple[str, str, float]] = [
    ("patient_name", r"patient(?:'s)? name|patient", 0.93),
    ("patient_name", r"name", 0.7),
    ("birth_date", r"date of birth|birth ?date|d\.?o\.?b\.?", 0.95),
    ("mrn", r"mrn|medical record (?:number|#|no\.?)", 0.95),
    ("phone", r"(?:patient )?(?:phone|tel(?:ephone)?|mobile|cell)", 0.85),
    ("insurance_payer", r"insurance(?: plan| payer| carrier)?|payer|health plan", 0.9),
    ("member_id", r"member (?:id|#|number)|subscriber (?:id|#)|policy (?:id|#|number)", 0.95),
    ("referring_provider", r"referring (?:provider|physician|clinician)|ordering provider", 0.93),
    ("referring_npi", r"(?:referring |provider )?npi", 0.95),
    ("specialty_requested", r"specialty(?: requested)?|refer(?:ral)? to", 0.9),
    ("reason_for_referral", r"reason for referral|referral reason", 0.93),
    ("reason_for_referral", r"reason|indication", 0.72),
    ("diagnosis_code", r"diagnosis code|icd-?10(?: code)?|dx(?: code)?", 0.93),
]

_LINE = re.compile(
    r"^[ \t]*(?P<label>[A-Za-z][A-Za-z0-9 '#./()-]{1,40}?)[ \t]*:[ \t]*"
    r"(?P<value>[^\r\n]*?)[ \t]*$",
    re.MULTILINE,
)
_DATE_FORMATS = (
    re.compile(r"^(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})$"),
    re.compile(r"^(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{4})$"),
)
_ICD10 = re.compile(r"^[A-TV-Z]\d[0-9AB](?:\.?[0-9A-TV-Z]{1,4})?$")
_NPI = re.compile(r"^\d{10}$")
_PHONE = re.compile(r"^\+?[\d\s().-]{7,20}$")
_MEMBER = re.compile(r"^[A-Za-z0-9-]{4,30}$")


def _valid_date(v: str) -> bool:
    for pat in _DATE_FORMATS:
        if m := pat.match(v):
            try:
                d = date(int(m["y"]), int(m["m"]), int(m["d"]))
            except ValueError:
                return False
            return date(1900, 1, 1) <= d <= date.today()
    return False


def _npi_checksum(npi: str) -> bool:
    """Luhn check with the 80840 prefix, per CMS NPI specification."""
    digits = [int(c) for c in "80840" + npi]
    total = 0
    for i, dgt in enumerate(reversed(digits)):
        if i % 2 == 1:
            dgt *= 2
            if dgt > 9:
                dgt -= 9
        total += dgt
    return total % 10 == 0


def format_ok(name: str, value: str) -> bool:
    v = value.strip()
    if name == "birth_date":
        return _valid_date(v)
    if name == "referring_npi":
        return bool(_NPI.match(v)) and _npi_checksum(v)
    if name == "diagnosis_code":
        return bool(_ICD10.match(v.upper()))
    if name == "phone":
        return bool(_PHONE.match(v)) and sum(c.isdigit() for c in v) >= 10
    if name == "member_id":
        return bool(_MEMBER.match(v))
    return len(v) >= 2


def _field_for(label: str) -> tuple[str, float] | None:
    lab = label.strip().lower()
    for name, pattern, conf in _LABELS:
        if re.fullmatch(pattern, lab):
            return name, conf
    return None


def _split_value(name: str, value: str, offset: int) -> tuple[str, int] | None:
    """Trim a value to its meaningful head, e.g. 'Medicaid — Plan ID X' stays whole but
    'I10 Essential hypertension' yields the code."""
    if name == "diagnosis_code":
        m = re.match(r"[A-Za-z]\d[0-9A-Ba-b](?:\.?[0-9A-Za-z]{1,4})?", value)
        return (m.group(0), offset) if m else None
    if name == "referring_npi":
        m = re.search(r"\d{10}", value)
        return (m.group(0), offset + m.start()) if m else None
    return value, offset


def extract_fields(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    for m in _LINE.finditer(text):
        found = _field_for(m["label"])
        if not found:
            continue
        name, conf = found
        raw = m["value"]
        if not raw or _field_for(raw.split(":")[0]) and ":" in raw:
            continue
        split = _split_value(name, raw, m.start("value"))
        if not split:
            continue
        value, start = split
        if value.strip().lower() in {"n/a", "na", "none", "unknown", "-", "pending", "tbd"}:
            continue  # an explicit blank is a missing value, never a value
        if not format_ok(name, value):
            conf = min(conf, 0.35)
        cand = Candidate(name, value, start, start + len(value), round(conf, 2))
        if grounded(text, cand):
            out.append(cand)
    return out


def grounded(text: str, cand: Candidate) -> bool:
    """True only when the cited span reproduces the value exactly."""
    if not cand.value.strip() or cand.start < 0 or cand.end > len(text) or cand.start >= cand.end:
        return False
    return text[cand.start : cand.end] == cand.value


def normalize(name: str, value: str) -> str:
    v = " ".join(value.split()).strip().lower()
    if name == "birth_date":
        for pat in _DATE_FORMATS:
            if m := pat.match(v):
                return f"{int(m['y']):04d}-{int(m['m']):02d}-{int(m['d']):02d}"
    if name in ("phone", "referring_npi", "member_id"):
        return re.sub(r"[^0-9a-z]", "", v)
    if name == "diagnosis_code":
        return v.replace(".", "").upper()
    return v
