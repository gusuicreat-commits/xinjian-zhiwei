from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_any_role, require_permission
from app.db.session import get_db
from app.experiment_packages.loader import (
    ExperimentPackageLoadError,
    load_experiment_package_payload,
)
from app.models.classroom import User
from app.models.experiment import (
    Experiment,
    ExperimentTemplate,
    ExperimentTemplateVersion,
    ExperimentVersion,
)
from app.schemas.experiment import (
    ExperimentPackageImport,
    ExperimentPackageStatusUpdate,
    ExperimentPackageVersionResponse,
    TemplateContentUpdate,
    TemplateCreate,
    TemplateStatusUpdate,
    TemplateVersionCreate,
    TemplateVersionResponse,
)
from app.services.experiment_packages import (
    import_experiment_package,
    transition_experiment_package,
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
PackagePublisher = Annotated[User, Depends(require_any_role("admin"))]


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


def _package_response(
    experiment: Experiment,
    version: ExperimentVersion,
) -> ExperimentPackageVersionResponse:
    return ExperimentPackageVersionResponse(
        id=version.id,
        experiment_id=experiment.id,
        experiment_code=experiment.code,
        experiment_name=experiment.name,
        version=version.version,
        schema_version=version.schema_version,
        engine_compatibility=version.engine_compatibility,
        package_hash=version.package_hash,
        status=version.status,
        is_current=version.is_current,
        validation_report=version.validation_report,
        is_test_data=version.is_test_data,
    )


@router.post("/packages/validate")
def validate_package(
    payload: ExperimentPackageImport,
    _: TemplateManager,
) -> dict:
    try:
        _, report = load_experiment_package_payload(payload.documents)
    except ExperimentPackageLoadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return report.model_dump(mode="json")


@router.post(
    "/packages/import",
    response_model=ExperimentPackageVersionResponse,
    status_code=201,
)
def import_package(
    payload: ExperimentPackageImport,
    actor: TemplateManager,
    db: DatabaseSession,
) -> ExperimentPackageVersionResponse:
    try:
        experiment, version = import_experiment_package(
            db,
            actor,
            payload.documents,
            is_test_data=payload.is_test_data,
        )
    except ExperimentPackageLoadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _package_response(experiment, version)


@router.get("/package-versions", response_model=list[ExperimentPackageVersionResponse])
def list_package_versions(
    _: TemplateManager,
    db: DatabaseSession,
) -> list[ExperimentPackageVersionResponse]:
    versions = list(
        db.scalars(
            select(ExperimentVersion).order_by(
                ExperimentVersion.created_at.desc(), ExperimentVersion.id.desc()
            )
        )
    )
    experiments = {
        item.id: item
        for item in db.scalars(
            select(Experiment).where(Experiment.id.in_({item.experiment_id for item in versions}))
        )
    }
    return [_package_response(experiments[item.experiment_id], item) for item in versions]


@router.post(
    "/package-versions/{version_id}/status",
    response_model=ExperimentPackageVersionResponse,
)
def change_package_status(
    version_id: str,
    payload: ExperimentPackageStatusUpdate,
    actor: PackagePublisher,
    db: DatabaseSession,
) -> ExperimentPackageVersionResponse:
    version = db.get(ExperimentVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="experiment package version not found")
    try:
        transition_experiment_package(db, actor, version, payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    experiment = db.get(Experiment, version.experiment_id)
    return _package_response(experiment, version)


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
