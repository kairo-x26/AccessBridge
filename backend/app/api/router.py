from fastapi import APIRouter

from app.api.v1 import (
    agents,
    audit,
    auth,
    integrations,
    providers,
    referrals,
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
):
    api.include_router(r)
