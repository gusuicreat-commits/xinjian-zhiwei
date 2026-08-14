from fastapi import APIRouter

from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.device import router as device_router
from app.api.v1.routes.diagnosis import router as diagnosis_router
from app.api.v1.routes.diagnosis_workflows import router as diagnosis_workflows_router
from app.api.v1.routes.experiments import router as experiments_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.interventions import router as interventions_router
from app.api.v1.routes.knowledge import router as knowledge_router
from app.api.v1.routes.readiness import router as readiness_router
from app.api.v1.routes.student import router as student_router
from app.api.v1.routes.teacher import router as teacher_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(health_router)
api_router.include_router(knowledge_router)
api_router.include_router(interventions_router)
api_router.include_router(readiness_router)
api_router.include_router(device_router)
api_router.include_router(diagnosis_router)
api_router.include_router(diagnosis_workflows_router)
api_router.include_router(experiments_router)
api_router.include_router(student_router)
api_router.include_router(teacher_router)
