from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.db.session import get_db
from app.models.classroom import User
from app.models.experiment import ExperimentTemplate, ExperimentTemplateVersion
from app.schemas.experiment import (
    TemplateContentUpdate,
    TemplateCreate,
    TemplateStatusUpdate,
    TemplateVersionCreate,
    TemplateVersionResponse,
)
from app.services.experiment_templates import (
    create_template,
    create_template_version,
    get_template_version,
    transition,
    update_content,
)

router = APIRouter(prefix="/experiments", tags=["experiments"])
DatabaseSession = Annotated[Session, Depends(get_db)]
TemplateManager = Annotated[User, Depends(require_permission("assignment.manage"))]


def _response(
    template: ExperimentTemplate,
    version: ExperimentTemplateVersion,
) -> TemplateVersionResponse:
    return TemplateVersionResponse(
        id=version.id,
        template_id=template.id,
        code=template.code,
        title=template.title,
        version=version.version,
        status=version.status,
        content=version.content_json,
        content_hash=version.content_hash,
        missing_fields=version.missing_fields_json,
        is_test_data=template.is_test_data,
    )


@router.post("/templates", response_model=TemplateVersionResponse, status_code=201)
def create(
    payload: TemplateCreate,
    actor: TemplateManager,
    db: DatabaseSession,
) -> TemplateVersionResponse:
    template, version = create_template(
        db,
        actor,
        code=payload.code,
        title=payload.title,
        description=payload.description,
        version=payload.version,
        content=payload.content,
        is_test_data=payload.is_test_data,
    )
    return _response(template, version)


@router.post(
    "/templates/{template_id}/versions",
    response_model=TemplateVersionResponse,
    status_code=201,
)
def create_version(
    template_id: str,
    payload: TemplateVersionCreate,
    actor: TemplateManager,
    db: DatabaseSession,
) -> TemplateVersionResponse:
    template = db.get(ExperimentTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template not found")
    version = create_template_version(
        db,
        actor,
        template,
        version=payload.version,
        content=payload.content,
    )
    return _response(template, version)


@router.patch("/template-versions/{version_id}", response_model=TemplateVersionResponse)
def edit(
    version_id: str,
    payload: TemplateContentUpdate,
    actor: TemplateManager,
    db: DatabaseSession,
) -> TemplateVersionResponse:
    version = get_template_version(db, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="template version not found")
    template = db.get(ExperimentTemplate, version.template_id)
    try:
        update_content(db, actor, version, payload.content)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _response(template, version)


@router.post(
    "/template-versions/{version_id}/status",
    response_model=TemplateVersionResponse,
)
def change_status(
    version_id: str,
    payload: TemplateStatusUpdate,
    actor: TemplateManager,
    db: DatabaseSession,
) -> TemplateVersionResponse:
    version = get_template_version(db, version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    template = db.get(ExperimentTemplate, version.template_id)
    try:
        transition(db, actor, version, payload.status)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _response(template, version)
