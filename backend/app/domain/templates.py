"""Built-in patient message wording and the rules every template must follow (FR-11, FR-15).

Built-ins are starting points. An organization adopts a template by saving it and having a
second staff member review it; only reviewed, active templates can be sent. Messages are
administrative: they never mention diagnoses, reasons or results.
"""

from __future__ import annotations

import string

LANGUAGES = {
    "en": "English",
    "es": "Spanish",
    "vi": "Vietnamese",
    "zh": "Chinese",
    "ar": "Arabic",
    "ht": "Haitian Creole",
}

VARIABLES = {
    "first_name": "Patient's first name",
    "clinic_name": "Your clinic's name",
    "specialist_office": "Destination specialist office",
    "specialist_phone": "Specialist office phone",
}

KEYS = {
    "schedule_prompt": "Ask the patient to schedule with the specialist",
    "appointment_check": "Ask whether the specialist visit happened",
}

BUILTIN: dict[tuple[str, str], str] = {
    ("schedule_prompt", "en"): (
        "Hi {first_name}, this is {clinic_name}. Your referral was sent to "
        "{specialist_office}. Please call them at {specialist_phone} to schedule. Reply 1 if "
        "you have an appointment, 2 if you need help, 3 if you no longer want this referral. "
        "Reply STOP to opt out."
    ),
    ("schedule_prompt", "es"): (
        "Hola {first_name}, le escribe {clinic_name}. Su referido fue enviado a "
        "{specialist_office}. Por favor llame al {specialist_phone} para hacer una cita. "
        "Responda 1 si ya tiene cita, 2 si necesita ayuda, 3 si ya no desea este referido. "
        "Responda STOP para no recibir mensajes."
    ),
    ("appointment_check", "en"): (
        "Hi {first_name}, this is {clinic_name}. Did you see the specialist at "
        "{specialist_office}? Reply 1 if you went, 2 if you need to reschedule or need help. "
        "Reply STOP to opt out."
    ),
    ("appointment_check", "es"): (
        "Hola {first_name}, le escribe {clinic_name}. ¿Pudo ver al especialista en "
        "{specialist_office}? Responda 1 si fue, 2 si necesita cambiar la cita o necesita "
        "ayuda. Responda STOP para no recibir mensajes."
    ),
}

MAX_LENGTH = 480
# Words that would make a message clinical rather than administrative.
_CLINICAL_WORDS = (
    "diagnos",
    "result",
    "test",
    "cancer",
    "tumor",
    "positive",
    "negative",
    "medication",
    "dose",
    "symptom",
)


def placeholders(body: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(body) if name is not None}


def problems(body: str) -> list[str]:
    out = []
    try:
        names = placeholders(body)
    except ValueError:
        return ["Template has unbalanced braces."]
    unknown = names - set(VARIABLES)
    if unknown:
        out.append(f"Unknown placeholders: {', '.join(sorted(unknown))}.")
    if len(body) > MAX_LENGTH:
        out.append(f"Keep messages under {MAX_LENGTH} characters.")
    if "STOP" not in body:
        out.append("Include opt-out instructions (Reply STOP).")
    lower = body.lower()
    hits = [w for w in _CLINICAL_WORDS if w in lower]
    if hits:
        out.append(
            f"Messages must stay administrative; remove clinical wording ({', '.join(hits)})."
        )
    return out


def render(body: str, values: dict[str, str]) -> str:
    return body.format_map({k: values.get(k, "") for k in VARIABLES})
