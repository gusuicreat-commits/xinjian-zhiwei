from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_authenticated_device, require_review_access
from app.db.session import get_db
from app.diagnosis.fault_tree_schemas import (
    GuidanceRecordResponse,
    GuidanceRunResponse,
    InterventionItem,
)
from app.diagnosis.schemas import DiagnosisMatch, DiagnosisRunRequest, DiagnosisRunResponse
from app.models.device import Device
from app.models.diagnosis_result import DiagnosisResult
from app.models.guidance_history import GuidanceHistory
from app.services.diagnosis import build_diagnosis_context, diagnose, save_diagnosis_result
from app.services.guidance import (
    generate_guidance,
    history_to_evaluation,
    list_device_guidance,
    list_interventions,
)

router = APIRouter(prefix="/diagnosis", tags=["diagnosis"])
AuthenticatedDevice = Annotated[Device, Depends(get_authenticated_device)]
DatabaseSession = Annotated[Session, Depends(get_db)]
ReviewAccess = Annotated[None, Depends(require_review_access)]


def _guidance_response(record: GuidanceHistory, device_key: str) -> GuidanceRecordResponse:
    evaluation = history_to_evaluation(record)
    return GuidanceRecordResponse(
        **evaluation.model_dump(),
        id=record.id,
        diagnosis_result_id=record.diagnosis_result_id,
        device_id=device_key,
        fault_tree_version=record.fault_tree_version,
        created_at=record.created_at,
    )


@router.post(
    "/devices/{device_id}/run",
    response_model=DiagnosisRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def run_device_diagnosis(
    device_id: str,
    payload: DiagnosisRunRequest,
    device: AuthenticatedDevice,
    db: DatabaseSession,
) -> DiagnosisRunResponse:
    if device_id != device.device_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="device id mismatch")
    context = build_diagnosis_context(
        db,
        device,
        lookback_seconds=payload.lookback_seconds,
        experiment_template=payload.experiment_template,
    )
    outcome = diagnose(context)
    record = save_diagnosis_result(db, device, context, outcome)
    return DiagnosisRunResponse(
        id=record.id,
        device_id=device.device_key,
        evaluated_at=record.evaluated_at,
        ruleset_version=record.ruleset_version,
        input_fingerprint=record.input_fingerprint,
        matches=[DiagnosisMatch.model_validate(match) for match in record.matched_rules],
        is_test_data=record.is_test_data,
        created_at=record.created_at,
    )


@router.post(
    "/results/{diagnosis_result_id}/guidance",
    response_model=GuidanceRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def run_guidance(
    diagnosis_result_id: str,
    device: AuthenticatedDevice,
    db: DatabaseSession,
) -> GuidanceRunResponse:
    diagnosis_result = db.scalar(
        select(DiagnosisResult).where(DiagnosisResult.id == diagnosis_result_id)
    )
    if diagnosis_result is None or diagnosis_result.device_id != device.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="diagnosis not found")
    records = generate_guidance(db, device, diagnosis_result)
    return GuidanceRunResponse(
        items=[_guidance_response(record, device.device_key) for record in records]
    )


@router.get(
    "/devices/{device_id}/guidance",
    response_model=list[GuidanceRecordResponse],
)
def get_device_guidance(
    device_id: str,
    device: AuthenticatedDevice,
    db: DatabaseSession,
) -> list[GuidanceRecordResponse]:
    if device_id != device.device_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="device id mismatch")
    return [
        _guidance_response(record, device.device_key) for record in list_device_guidance(db, device)
    ]


@router.get("/interventions", response_model=list[InterventionItem])
def get_interventions(
    _: ReviewAccess,
    db: DatabaseSession,
) -> list[InterventionItem]:
    return [
        InterventionItem(
            device_id=record.device.device_key,
            diagnosis_result_id=record.diagnosis_result_id,
            tree_id=record.fault_tree_id,
            tree_title=record.fault_tree_title,
            hint_level=4,
            failure_count=record.failure_count,
            anomaly_duration_seconds=record.anomaly_duration_seconds,
            created_at=record.created_at,
        )
        for record in list_interventions(db)
    ]
