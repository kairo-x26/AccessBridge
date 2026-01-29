from __future__ import annotations

import io

from app.evaluation.extraction import report
from app.services import document_ai as dai


def test_extraction_meets_acceptance_on_template_corpus():
    out = report(n=300)
    assert out["critical"]["precision"] >= 0.95
    assert out["critical"]["recall"] >= 0.95


def test_unseen_wording_never_lowers_precision():
    out = report(n=200, seed=11, unseen=True)
    assert out["critical"]["precision"] >= 0.99


def test_explicit_blanks_are_not_values():
    fields = dai.extract_fields("Member ID: N/A\nInsurance: unknown\nDOB: 1970-01-01")
    assert [f.name for f in fields] == ["birth_date"]


def test_spans_point_at_the_value():
    text = "Header\nPatient Name:  Rosa Delgado  \nDOB: 03/14/1968"
    for f in dai.extract_fields(text):
        assert text[f.start : f.end] == f.value


def test_grounding_rejects_invented_values():
    text = "Patient Name: Rosa Delgado"
    assert not dai.grounded(text, dai.Candidate("member_id", "MBR-1", 0, 5, 0.99, "llm"))
    assert not dai.grounded(text, dai.Candidate("patient_name", "Rosa Delgado", 0, 12, 0.9))
    assert dai.grounded(text, dai.Candidate("patient_name", "Rosa Delgado", 14, 26, 0.9))


def test_malformed_values_get_low_confidence():
    f = {c.name: c for c in dai.extract_fields("DOB: 02/30/1980\nNPI: 1234567890")}
    assert f["birth_date"].confidence < 0.6
    assert f["referring_npi"].confidence < 0.6  # fails Luhn check


def test_classification():
    assert dai.classify("Member ID: X\nGroup #: 4\nCopay $20", "card.jpg")[0] == "insurance_card"
    assert dai.classify("Reason for referral: x\nSpecialty requested: y")[0] == "referral_form"
    assert dai.classify("X-ray left knee. Findings: ... Impression: OA")[0] == "imaging_report"
    assert dai.classify("Thank you for this referral. Consultation note.")[0] == "consult_note"
    assert dai.classify("hello")[0] == "other"


def test_text_extraction_paths():
    assert dai.extract_text(b"hi", "text/plain") == ("hi", "done")
    assert dai.extract_text(b"\x89PNG", "image/png") == (None, "needs_ocr")
    assert dai.extract_text(b"not a pdf", "application/pdf")[1] == "failed"
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(100, 100)
    buf = io.BytesIO()
    w.write(buf)
    assert dai.extract_text(buf.getvalue(), "application/pdf") == (None, "needs_ocr")


def test_normalize():
    assert dai.normalize("birth_date", "3/14/1968") == "1968-03-14"
    assert dai.normalize("diagnosis_code", "m17.11") == "M1711"
