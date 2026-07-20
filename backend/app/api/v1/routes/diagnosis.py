from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_authenticated_device
from app.db.session import get_db
from app.diagnosis.schemas import DiagnosisMatch, DiagnosisRunRequest, DiagnosisRunResponse
from app.models.device import Device
from app.services.diagnosis import build_diagnosis_context, diagnose, save_diagnosis_result

router = APIRouter(prefix="/diagnosis", tags=["diagnosis"])
AuthenticatedDevice = Annotated[Device, Depends(get_authenticated_device)]
DatabaseSession = Annotated[Session, Depends(get_db)]


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
