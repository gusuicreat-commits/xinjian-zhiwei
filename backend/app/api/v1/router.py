from fastapi import APIRouter

from app.api.v1.routes.device import router as device_router
from app.api.v1.routes.diagnosis import router as diagnosis_router
from app.api.v1.routes.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(device_router)
api_router.include_router(diagnosis_router)
