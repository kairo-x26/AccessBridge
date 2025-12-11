"""Approved file-format intake: CSV referral exports (FR-03 alternative route)."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from app.integrations.fhir import normalize_specialty
from app.services.referrals import IntakeRecord, PatientIn

SOURCE_SYSTEM = "csv"
REQUIRED = ("source_id", "ehr_patient_id", "given_name", "family_name", "specialty")
OPTIONAL = (
    "birth_date",
    "phone",
    "email",
    "preferred_language",
    "priority",
    "reason",
    "referring_clinician",
    "provider_name",
)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_ROWS = 5000


@dataclass
class CsvParse:
    records: list[IntakeRecord] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)


def parse_csv(text: str) -> CsvParse:
    out = CsvParse()
    reader = csv.DictReader(io.StringIO(text))
    headers = {h.strip().lower() for h in (reader.fieldnames or [])}
    missing = [h for h in REQUIRED if h not in headers]
    if missing:
        out.errors.append({"row": "header", "error": f"Missing columns: {', '.join(missing)}"})
        return out
    for i, raw in enumerate(reader, start=2):
        if i - 1 > MAX_ROWS:
            out.errors.append({"row": str(i), "error": f"File has more than {MAX_ROWS} rows"})
            break
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        empty = [h for h in REQUIRED if not row.get(h)]
        if empty:
            out.errors.append({"row": str(i), "error": f"Empty required: {', '.join(empty)}"})
            continue
        if row.get("birth_date") and not _DATE.match(row["birth_date"]):
            out.errors.append({"row": str(i), "error": "birth_date must be YYYY-MM-DD"})
            continue
        priority = (row.get("priority") or "routine").lower()
        if priority not in ("routine", "urgent", "asap", "stat"):
            out.errors.append({"row": str(i), "error": f"Unknown priority {priority!r}"})
            continue
        out.records.append(
            IntakeRecord(
                source_system=SOURCE_SYSTEM,
                source_id=row["source_id"],
                patient=PatientIn(
                    ehr_patient_id=row["ehr_patient_id"],
                    given_name=row["given_name"],
                    family_name=row["family_name"],
                    birth_date=row.get("birth_date") or None,
                    phone=row.get("phone") or None,
                    email=row.get("email") or None,
                    preferred_language=(row.get("preferred_language") or "en").lower()[:5],
                ),
                specialty=normalize_specialty(row["specialty"]),
                priority_from_source=priority,
                reason_from_source=row.get("reason") or None,
                referring_clinician=row.get("referring_clinician") or None,
                provider_name=row.get("provider_name") or None,
            )
        )
    return out
