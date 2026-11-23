from fastapi import APIRouter

from app.api.v1 import admin, auth, items, uploads

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(items.router)
api_router.include_router(admin.router)
api_router.include_router(uploads.router)
