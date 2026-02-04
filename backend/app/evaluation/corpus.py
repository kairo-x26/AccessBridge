"""Synthetic referral-document corpus with ground truth, for extraction evaluation.

Documents vary label wording, ordering, date formats, noise lines, missing fields and
explicit blanks ("N/A") so that precision and recall are measured honestly. All data is
fictional and generated deterministically from a seed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

GIVEN = [
    "Rosa",
    "James",
    "Mei",
    "Amina",
    "Luis",
    "Grace",
    "Tomas",
    "Priya",
    "Samuel",
    "Ivy",
    "Daniel",
    "Fatima",
    "Noah",
    "Elena",
    "Kwame",
    "Lucia",
]
FAMILY = [
    "Delgado",
    "Whitfield",
    "Tanaka",
    "Hassan",
    "Moreno",
    "Okafor",
    "Novak",
    "Raman",
    "Brooks",
    "Chen",
    "Alvarez",
    "Yusuf",
    "Kim",
    "Petrov",
    "Mensah",
    "Romero",
]
PAYERS = [
    "Medicaid — Plan ID MCD-448812",
    "Blue Prairie PPO",
    "Riverbend Health Plan",
    "Medicare Part B",
    "Sunrise Community Care HMO",
]
REASONS = [
    "Evaluate persistent palpitations",
    "Chronic knee pain, failed PT",
    "Suspicious skin lesion on left forearm",
    "Uncontrolled type 2 diabetes",
    "Recurrent migraines",
    "Blurred vision, diabetic eye exam",
    "Chronic abdominal pain",
    "Anxiety, medication management",
]
SPECIALTIES = [
    "Cardiology",
    "Orthopedics",
    "Dermatology",
    "Endocrinology",
    "Neurology",
    "Ophthalmology",
    "Gastroenterology",
    "Behavioral Health",
]
ICD = ["I10", "M17.11", "L98.9", "E11.65", "G43.909", "H35.00", "R10.9", "F41.1"]
NPIS = ["1457382913", "1234567893", "1003000126", "1497758544"]

LABELS = {
    "patient_name": ["Patient Name", "Patient", "Name"],
    "birth_date": ["Date of Birth", "DOB", "Birth Date"],
    "mrn": ["MRN", "Medical Record Number"],
    "insurance_payer": ["Insurance", "Payer", "Health Plan"],
    "member_id": ["Member ID", "Subscriber ID", "Policy Number"],
    "referring_provider": ["Referring Provider", "Referring Physician", "Ordering Provider"],
    "referring_npi": ["Referring NPI", "NPI"],
    "reason_for_referral": ["Reason for Referral", "Reason", "Indication"],
    "diagnosis_code": ["Diagnosis Code", "ICD-10", "Dx"],
}
# Wordings the extractor has never seen; measures robustness rather than fit.
UNSEEN_LABELS = {
    "patient_name": ["Pt Name", "Client"],
    "birth_date": ["Birthdate", "D.O.B"],
    "mrn": ["Chart #", "Record ID"],
    "insurance_payer": ["Ins", "Coverage"],
    "member_id": ["Member No", "ID Number"],
    "referring_provider": ["From", "PCP"],
    "referring_npi": ["Prov NPI #", "National Provider ID"],
    "reason_for_referral": ["Clinical Question", "Why referred"],
    "diagnosis_code": ["Dx Code", "Primary ICD"],
}
NOISE = [
    "Fax cover: 2 pages",
    "Please call with questions.",
    "Office hours 8-5 M-F",
    "CONFIDENTIAL HEALTH INFORMATION",
    "Note: patient prefers mornings",
    "Comments: see attached",
]


@dataclass
class Sample:
    text: str
    truth: dict[str, str]  # field -> exact expected value (absent = not present in document)


def make_sample(rng: random.Random, unseen: bool = False) -> Sample:
    given, family = rng.choice(GIVEN), rng.choice(FAMILY)
    y, m, d = rng.randint(1940, 2005), rng.randint(1, 12), rng.randint(1, 28)
    dob = rng.choice([f"{y:04d}-{m:02d}-{d:02d}", f"{m:02d}/{d:02d}/{y:04d}"])
    i = rng.randrange(len(REASONS))
    values = {
        "patient_name": f"{given} {family}",
        "birth_date": dob,
        "mrn": f"{rng.randint(100000, 999999)}",
        "insurance_payer": rng.choice(PAYERS),
        "member_id": f"MBR-{rng.randint(10_000_000, 99_999_999)}",
        "referring_provider": f"Dr. {rng.choice(GIVEN)} {rng.choice(FAMILY)}",
        "referring_npi": rng.choice(NPIS),
        "reason_for_referral": REASONS[i],
        "diagnosis_code": ICD[i],
    }
    truth: dict[str, str] = {"specialty_requested": SPECIALTIES[i]}
    lines = ["SPECIALTY REFERRAL", f"Specialty Requested: {SPECIALTIES[i]}"]
    order = list(values)
    rng.shuffle(order)
    for name in order:
        roll = rng.random()
        label = rng.choice((UNSEEN_LABELS if unseen else LABELS)[name])
        if roll < 0.08:
            continue  # field absent
        if roll < 0.12:
            lines.append(f"{label}: N/A")  # explicit blank: must not be extracted
            continue
        value = values[name]
        if name == "diagnosis_code" and rng.random() < 0.4:
            lines.append(f"{label}: {value} {REASONS[i].split(',')[0].lower()}")
        else:
            lines.append(f"{label}: {value}")
        truth[name] = value
        if rng.random() < 0.2:
            lines.append(rng.choice(NOISE))
    lines.append("Signed electronically.")
    return Sample("\n".join(lines), truth)


def corpus(n: int = 300, seed: int = 7, unseen: bool = False) -> list[Sample]:
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic data, not security
    return [make_sample(rng, unseen) for _ in range(n)]
