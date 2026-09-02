from app.models.ai_call_record import AICallRecord
from app.models.ai_explanation_cache import AIExplanationCache
from app.models.classroom import (
    AuditEvent,
    AuthSession,
    Classroom,
    Course,
    DeviceBinding,
    Enrollment,
    ExperimentAssignment,
    ExperimentSession,
    Permission,
    Role,
    TeachingAssignment,
    User,
)
from app.models.device import Device
from app.models.device_heartbeat import DeviceHeartbeat
from app.models.device_log import DeviceLog
from app.models.diagnosis_episode import DiagnosisEpisode
from app.models.diagnosis_feedback import DiagnosisFeedback
from app.models.diagnosis_result import DiagnosisResult
from app.models.diagnosis_workflow import DiagnosisWorkflowReview, DiagnosisWorkflowRun
from app.models.experiment import (
    DiagnosticArtifact,
    ExperimentTemplate,
    ExperimentTemplateVersion,
)
from app.models.guidance_history import GuidanceHistory
from app.models.ingestion_request import IngestionRequest
from app.models.intervention import ClassroomMessage, InterventionCase, InterventionEvent
from app.models.knowledge import (
    KnowledgeCase,
    KnowledgeCaseDraft,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeReview,
    KnowledgeSource,
)
from app.models.sensor_reading import SensorReading

__all__ = [
    "AICallRecord",
    "AIExplanationCache",
    "AuditEvent",
    "AuthSession",
    "Classroom",
    "ClassroomMessage",
    "Course",
    "Device",
    "DeviceBinding",
    "DeviceHeartbeat",
    "DeviceLog",
    "DiagnosisFeedback",
    "DiagnosisResult",
    "DiagnosisWorkflowReview",
    "DiagnosisWorkflowRun",
    "DiagnosticArtifact",
    "Enrollment",
    "ExperimentAssignment",
    "ExperimentSession",
    "ExperimentTemplate",
    "ExperimentTemplateVersion",
    "DiagnosisEpisode",
    "GuidanceHistory",
    "IngestionRequest",
    "InterventionCase",
    "InterventionEvent",
    "KnowledgeChunk",
    "KnowledgeCase",
    "KnowledgeCaseDraft",
    "KnowledgeDocument",
    "KnowledgeReview",
    "KnowledgeSource",
    "Permission",
    "Role",
    "SensorReading",
    "TeachingAssignment",
    "User",
]
