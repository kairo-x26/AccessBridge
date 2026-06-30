from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response

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


Exporter = Annotated[Principal, Depends(require(Perm.REPORT_EXPORT))]


@router.get("/referrals.csv")
def referral_export(
    principal: Exporter,
    session: DB,
    specialty: str | None = None,
    since_days: int | None = Query(None, ge=1, le=3650),
) -> Response:
    """Aggregate export by specialty and status. Small counts are suppressed (FR-21)."""
    import csv
    import io

    from sqlalchemy import func, select

    from app.models import Organization, Referral

    org = session.get(Organization, principal.organization_id)
    min_cell = int((org.configuration if org else {}).get("export_min_cell", 5))
    q = select(Referral.specialty, Referral.status, func.count()).where(
        Referral.organization_id == principal.organization_id
    )
    if specialty:
        q = q.where(Referral.specialty == specialty)
    if since_days:
        q = q.where(Referral.created_at >= utcnow() - timedelta(days=since_days))
    rows = session.execute(
        q.group_by(Referral.specialty, Referral.status).order_by(
            Referral.specialty, Referral.status
        )
    ).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["specialty", "status", "referrals"])
    for sp, st, n in rows:
        w.writerow([sp, st, f"<{min_cell}" if 0 < n < min_cell else n])
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="report.export",
        details={"rows": len(rows), "min_cell": min_cell},
    )
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={
            "content-disposition": 'attachment; filename="referral-summary.csv"',
            "cache-control": "no-store",
        },
    )
