from fastapi import APIRouter

from app.api.v1 import audit, auth, users

api = APIRouter(prefix="/v1")
for module in (auth, users, audit):
    api.include_router(module.router)
