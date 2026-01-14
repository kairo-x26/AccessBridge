from fastapi import APIRouter

from app.api.v1 import audit, auth, integrations, providers, referrals, tasks, users

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
):
    api.include_router(r)
