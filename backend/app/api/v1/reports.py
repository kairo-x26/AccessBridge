from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import DB, Principal, require
from app.core.db import utcnow
from app.domain.rbac import Perm
from app.services import audit, reports

router = APIRouter(prefix="/reports", tags=["reports"])
Reporter = Annotated[Principal, Depends(require(Perm.REPORT_READ))]


@router.get("/referrals")
def referral_metrics(
    principal: Reporter,
    session: DB,
    specialty: str | None = None,
    owner_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    since_days: int | None = Query(None, ge=1, le=3650),
) -> dict[str, Any]:
    """Authorized operational metrics (spec §9)."""
    if since_days and not since:
        since = utcnow() - timedelta(days=since_days)
    if owner_id == "me":
        owner_id = principal.user_id
    r = reports.build(
        session, principal.organization_id, reports.Filters(specialty, owner_id, since, until)
    )
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="report.view",
        details={"specialty": specialty},
    )
    return asdict(r)
