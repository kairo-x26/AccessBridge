from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select

from app.api.deps import DB, Principal, require
from app.api.v1.schemas import Page, TaskOut
from app.core.db import utcnow
from app.core.errors import ValidationFailed
from app.core.tenancy import get_scoped, scoped
from app.domain.rbac import Perm
from app.models import Referral, Task, User
from app.services import audit, tasks

router = APIRouter(prefix="/tasks", tags=["tasks"])
Reader = Annotated[Principal, Depends(require(Perm.TASK_READ))]
Manager = Annotated[Principal, Depends(require(Perm.TASK_MANAGE))]

KINDS = (
    "missing_info",
    "review_package",
    "approval",
    "follow_up",
    "exception",
    "patient_assistance",
    "reconciliation",
    "escalation",
    "other",
)
Priority = Literal["low", "normal", "high", "urgent"]


@router.get("", response_model=Page[TaskOut])
def list_tasks(
    principal: Reader,
    session: DB,
    status: Literal["open", "closed", "all"] = "open",
    owner: str | None = Query(None, description="'me', 'unassigned' or a user id"),
    kind: str | None = None,
    referral_id: str | None = None,
    overdue: bool = False,
    q: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Page[TaskOut]:
    stmt = scoped(Task, principal.organization_id)
    if status == "open":
        stmt = stmt.where(Task.status.in_(tasks.OPEN_STATES))
    elif status == "closed":
        stmt = stmt.where(Task.status.not_in(tasks.OPEN_STATES))
    if owner == "me":
        stmt = stmt.where(Task.owner_id == principal.user_id)
    elif owner == "unassigned":
        stmt = stmt.where(Task.owner_id.is_(None))
    elif owner:
        stmt = stmt.where(Task.owner_id == owner)
    if kind:
        stmt = stmt.where(Task.kind == kind)
    if referral_id:
        stmt = stmt.where(Task.referral_id == referral_id)
    if overdue:
        stmt = stmt.where(Task.due_at < utcnow(), Task.status.in_(tasks.OPEN_STATES))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(func.lower(Task.title).like(like), func.lower(Task.referral_id).like(like))
        )
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    prio = case({p: i for p, i in tasks.PRIORITY_ORDER.items()}, value=Task.priority, else_=9)
    rows = session.scalars(
        stmt.order_by(prio, Task.due_at.asc().nulls_last())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page[TaskOut](
        items=[TaskOut.model_validate(t) for t in rows], total=total, page=page, page_size=page_size
    )


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: str = "other"
    detail: str | None = Field(default=None, max_length=2000)
    referral_id: str | None = None
    owner_id: str | None = None
    priority: Priority = "normal"
    due_at: datetime | None = None


@router.post("", response_model=TaskOut, status_code=201)
def create_task(body: TaskIn, principal: Manager, session: DB) -> Task:
    if body.kind not in KINDS:
        raise ValidationFailed(f"Unknown task kind {body.kind!r}.")
    if body.referral_id:
        get_scoped(session, Referral, body.referral_id, principal.organization_id)
    if body.owner_id:
        get_scoped(session, User, body.owner_id, principal.organization_id)
    task, _ = tasks.ensure_task(
        session,
        organization_id=principal.organization_id,
        kind=body.kind,
        title=body.title,
        detail=body.detail,
        referral_id=body.referral_id,
        owner_id=body.owner_id,
        priority=body.priority,
        due_at=body.due_at,
        created_by=principal.actor,
    )
    return task


class TaskPatch(BaseModel):
    owner_id: str | None = None
    unassign: bool = False
    status: Literal["open", "in_progress", "done", "cancelled"] | None = None
    priority: Priority | None = None
    due_at: datetime | None = None
    resolution: str | None = Field(default=None, max_length=500)


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: str, body: TaskPatch, principal: Manager, session: DB) -> Task:
    task = get_scoped(session, Task, task_id, principal.organization_id)
    changes: dict[str, str | None] = {}
    if body.owner_id:
        get_scoped(session, User, body.owner_id, principal.organization_id)
        task.owner_id = body.owner_id
        changes["owner_id"] = body.owner_id
    elif body.unassign:
        task.owner_id = None
        changes["owner_id"] = None
    if body.priority:
        task.priority = body.priority
        changes["priority"] = body.priority
    if body.due_at:
        task.due_at = body.due_at
        changes["due_at"] = body.due_at.isoformat()
    if body.status in ("done", "cancelled"):
        if not body.resolution:
            raise ValidationFailed("Describe how the task was resolved.")
        tasks.resolve(
            session, task, actor=principal.actor, resolution=body.resolution, status=body.status
        )
    elif body.status:
        if task.status not in tasks.OPEN_STATES:
            task.resolved_at = None
            task.resolution = None
        task.status = body.status
        changes["status"] = body.status
    if changes:
        audit.record(
            session,
            organization_id=principal.organization_id,
            actor=principal.actor,
            operation="task.update",
            resource_ref=task.id,
            details=changes,
        )
    return task
