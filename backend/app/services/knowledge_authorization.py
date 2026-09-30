"""Current reviewer identity and the recorded case scope, shared by all writes."""

from sqlalchemy import select

from app.models.classroom import (
    DeviceBinding,
    ExperimentAssignment,
    ExperimentSession,
    TeachingAssignment,
)
from app.models.diagnosis_feedback import DiagnosisFeedback
from app.models.diagnosis_result import DiagnosisResult
from app.models.knowledge import KnowledgeCaseDraft
from app.services.auth import AuthorizationDenied, authorize_actor, user_access


def reviewable_case_drafts(actor, roles):
    query = select(KnowledgeCaseDraft)
    if "formal_approver" in roles:
        return query
    return (
        query.join(DiagnosisFeedback, DiagnosisFeedback.id == KnowledgeCaseDraft.feedback_id)
        .join(DiagnosisResult, DiagnosisResult.id == KnowledgeCaseDraft.diagnosis_result_id)
        .join(ExperimentSession, ExperimentSession.id == DiagnosisFeedback.experiment_session_id)
        .join(
            ExperimentAssignment,
            ExperimentAssignment.id == ExperimentSession.experiment_assignment_id,
        )
        .join(TeachingAssignment, TeachingAssignment.class_id == ExperimentAssignment.class_id)
        .join(
            DeviceBinding,
            (DeviceBinding.device_id == DiagnosisResult.device_id)
            & (DeviceBinding.class_id == ExperimentAssignment.class_id)
            & (DeviceBinding.student_user_id == ExperimentSession.student_user_id)
            & DeviceBinding.is_active.is_(True),
        )
        .where(
            DiagnosisFeedback.diagnosis_result_id == DiagnosisResult.id,
            DiagnosisFeedback.device_id == DiagnosisResult.device_id,
            ExperimentSession.device_id == DiagnosisResult.device_id,
            TeachingAssignment.user_id == actor.id,
        )
    )


def authorize_case_write(db, identity, draft_id):
    if identity is None:
        raise AuthorizationDenied(401)
    roles, _ = user_access(db, identity.user_id)
    permission = "knowledge.review.approve" if "formal_approver" in roles else "intervention.manage"
    actor = authorize_actor(db, identity, permission)
    roles, _ = user_access(db, actor.id)
    if not {"formal_approver", "teacher"}.intersection(roles):
        raise AuthorizationDenied()
    if draft_id is None:
        if "formal_approver" not in roles:
            raise AuthorizationDenied()
    elif (
        db.scalar(
            reviewable_case_drafts(actor, roles)
            .where(KnowledgeCaseDraft.id == draft_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        is None
    ):
        raise AuthorizationDenied()
    return actor
