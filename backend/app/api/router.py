from fastapi import APIRouter

from app.api.v1 import (
    agents,
    audit,
    auth,
    communications,
    dev,
    integrations,
    organization,
    policies,
    providers,
    referrals,
    reports,
    review,
    tasks,
    users,
)

api = APIRouter(prefix="/v1")
for r in (
    auth.router,
    users.router,
    audit.router,
    referrals.router,
    referrals.docs_router,
    tasks.router,
    providers.router,
    integrations.router,
    review.router,
    agents.router,
    communications.router,
    communications.webhooks,
    reports.router,
    policies.router,
    organization.router,
):
    api.include_router(r)

dev_api = APIRouter(prefix="/v1")
dev_api.include_router(dev.router)
