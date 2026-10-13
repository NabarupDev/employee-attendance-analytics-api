"""API v1 master router combining all resource endpoints."""

from fastapi import APIRouter

from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.analytics import router as analytics_router
from app.api.v1.endpoints.attendance import router as attendance_router
from app.api.v1.endpoints.corrections import router as corrections_router
from app.api.v1.endpoints.employees import router as employees_router

api_v1_router = APIRouter()

api_v1_router.include_router(employees_router)
api_v1_router.include_router(attendance_router)
api_v1_router.include_router(corrections_router)
api_v1_router.include_router(analytics_router)
api_v1_router.include_router(admin_router)
