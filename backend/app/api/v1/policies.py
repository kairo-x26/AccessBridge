from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.deps import DB, Principal, require
from app.core.db import utcnow
from app.core.errors import Forbidden, ValidationFailed
from app.core.tenancy import get_scoped, scoped
from app.domain.rbac import Perm
from app.models import PolicyDocument
from app.services import audit, document_ai, policy_rag

router = APIRouter(prefix="/policies", tags=["policies"])
Searcher = Annotated[Principal, Depends(require(Perm.POLICY_SEARCH))]
Manager = Annotated[Principal, Depends(require(Perm.POLICY_MANAGE))]


class PolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    version: int
    status: str
    source_filename: str | None
    uploaded_by: str
    approved_by: str | None
    approved_at: datetime | None
    flagged_passages: int
    created_at: datetime


class PolicyDetail(PolicyOut):
    content: str


@router.get("", response_model=list[PolicyOut])
def list_policies(principal: Searcher, session: DB) -> list[PolicyDocument]:
    return list(
        session.scalars(
            scoped(PolicyDocument, principal.organization_id)
            .where(PolicyDocument.status != "archived")
            .order_by(PolicyDocument.title, PolicyDocument.version.desc())
        )
    )


@router.get("/{policy_id}", response_model=PolicyDetail)
def get_policy(policy_id: str, principal: Searcher, session: DB) -> PolicyDocument:
    return get_scoped(session, PolicyDocument, policy_id, principal.organization_id)


@router.post("", response_model=PolicyOut, status_code=201)
async def upload_policy(
    principal: Manager,
    session: DB,
    title: str = Form(..., max_length=200),
    file: UploadFile = File(...),
) -> PolicyDocument:
    data = await file.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValidationFailed("Policy files must be under 2 MB.")
    ctype = (file.content_type or "").split(";")[0]
    if ctype in ("text/markdown", "text/x-markdown"):
        ctype = "text/plain"
    text, status = document_ai.extract_text(data, ctype)
    if not text or status != "done":
        raise ValidationFailed("Upload a text, Markdown or text-based PDF file.")
    version = (
        session.scalar(
            select(func.max(PolicyDocument.version)).where(
                PolicyDocument.organization_id == principal.organization_id,
                PolicyDocument.title == title.strip(),
            )
        )
        or 0
    ) + 1
    doc = PolicyDocument(
        organization_id=principal.organization_id,
        title=title.strip(),
        version=version,
        content=text,
        source_filename=file.filename,
        uploaded_by=principal.actor,
    )
    session.add(doc)
    session.flush()
    policy_rag.index_document(session, doc)
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="policy.upload",
        resource_ref=doc.id,
        details={"title": doc.title, "version": version, "flagged": doc.flagged_passages},
    )
    return doc


@router.post("/{policy_id}/approve", response_model=PolicyOut)
def approve_policy(policy_id: str, principal: Manager, session: DB) -> PolicyDocument:
    doc = get_scoped(session, PolicyDocument, policy_id, principal.organization_id)
    if doc.status != "draft":
        raise ValidationFailed("Only drafts can be approved.")
    if doc.uploaded_by == principal.actor:
        raise Forbidden("A different staff member must approve this procedure.")
    for older in session.scalars(
        scoped(PolicyDocument, principal.organization_id).where(
            PolicyDocument.title == doc.title, PolicyDocument.status == "approved"
        )
    ):
        older.status = "archived"
    doc.status, doc.approved_by, doc.approved_at = "approved", principal.actor, utcnow()
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="policy.approve",
        resource_ref=doc.id,
    )
    return doc


@router.post("/{policy_id}/archive", response_model=PolicyOut)
def archive_policy(policy_id: str, principal: Manager, session: DB) -> PolicyDocument:
    doc = get_scoped(session, PolicyDocument, policy_id, principal.organization_id)
    doc.status = "archived"
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="policy.archive",
        resource_ref=doc.id,
    )
    return doc


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class CitationOut(BaseModel):
    number: int
    document_id: str
    title: str
    version: int
    heading: str | None
    excerpt: str


class AnswerOut(BaseModel):
    found: bool
    answer: str
    citations: list[CitationOut]
    method: str
    warnings: list[str]


@router.post("/ask", response_model=AnswerOut)
def ask(body: AskIn, principal: Searcher, session: DB) -> AnswerOut:
    a = policy_rag.ask(session, principal.organization_id, body.question)
    # Questions may mention patients; the audit keeps a fingerprint, not the text.
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="policy.ask",
        outcome="found" if a.found else "not_found",
        details={
            "question_sha256": hashlib.sha256(body.question.encode()).hexdigest()[:16],
            "citations": [c.document_id for c in a.citations],
        },
    )
    return AnswerOut(
        found=a.found,
        answer=a.answer,
        method=a.method,
        warnings=a.warnings,
        citations=[CitationOut(**c.__dict__) for c in a.citations],
    )
