from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.experiment_packages.loader import (
    ExperimentPackageLoadError,
    load_experiment_package_payload,
    package_documents,
    package_fault_tree_document,
    package_rule_document,
    package_to_experiment_definition,
)
from app.experiment_packages.schemas import (
    ExperimentPackageBundle,
    PackageValidationReport,
)
from app.models.base import utc_now
from app.models.classroom import AuditEvent, User
from app.models.experiment import (
    Experiment,
    ExperimentPackageArtifact,
    ExperimentVersion,
)

PACKAGE_TRANSITIONS = {
    "draft": {"pending"},
    "pending": {"approved"},
    "approved": {"published"},
    "published": {"revoked", "superseded"},
    "superseded": set(),
    "revoked": set(),
}
RUNTIME_STATUSES = {"published", "superseded"}


@dataclass(frozen=True)
class ExperimentPackageRuntime:
    experiment: Experiment
    version: ExperimentVersion
    bundle: ExperimentPackageBundle
    definition: Any
    rule_document: dict[str, Any]
    fault_tree_document: dict[str, Any]


def _artifact_kind(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else path.removesuffix(".yaml")


def import_experiment_package(
    db: Session,
    actor: User,
    documents: dict[str, Any],
    *,
    is_test_data: bool = False,
) -> tuple[Experiment, ExperimentVersion]:
    """Validate and import a new immutable draft package version."""

    bundle, _ = load_experiment_package_payload(documents)
    # Persist and sign the fully parsed canonical snapshot. This prevents an
    # omitted optional field from producing one hash at import and another at runtime.
    snapshot = package_documents(bundle)
    bundle, report = load_experiment_package_payload(snapshot)
    identity = bundle.metadata.experiment
    experiment = db.scalar(select(Experiment).where(Experiment.code == identity.code))
    if experiment is None:
        experiment = Experiment(
            code=identity.code,
            name=identity.name,
            category=identity.category,
            locale=identity.locale,
            status="active",
            is_test_data=is_test_data,
        )
        db.add(experiment)
        db.flush()
    elif (
        experiment.name != identity.name
        or experiment.category != identity.category
        or experiment.locale != identity.locale
    ):
        raise ValueError("package identity conflicts with the existing experiment")

    release = bundle.metadata.package
    duplicate = db.scalar(
        select(ExperimentVersion).where(
            ExperimentVersion.experiment_id == experiment.id,
            ExperimentVersion.version == release.version,
        )
    )
    if duplicate is not None:
        raise ValueError("this experiment package version already exists and cannot be overwritten")

    version = ExperimentVersion(
        experiment_id=experiment.id,
        version=release.version,
        schema_version=bundle.metadata.schema_version,
        engine_compatibility=bundle.metadata.compatibility.engine,
        package_hash=bundle.manifest.package_hash,
        package_manifest=bundle.manifest.model_dump(mode="json"),
        package_content=snapshot,
        validation_report=report.model_dump(mode="json"),
        status="draft",
        is_current=False,
        created_by_user_id=actor.id,
        is_test_data=is_test_data,
    )
    db.add(version)
    db.flush()
    hashes = {item.path: item.sha256 for item in bundle.manifest.files}
    for path, content in snapshot.items():
        db.add(
            ExperimentPackageArtifact(
                experiment_version_id=version.id,
                kind=_artifact_kind(path),
                artifact_key=path,
                content_json=content,
                content_hash=hashes[path],
                source_path=path,
            )
        )
    db.add(
        AuditEvent(
            actor_user_id=actor.id,
            action="experiment_package.import",
            resource_type="experiment_version",
            resource_id=version.id,
            details_json={
                "experiment_code": experiment.code,
                "version": version.version,
                "package_hash": version.package_hash,
            },
            is_test_data=is_test_data,
            created_at=utc_now(),
        )
    )
    db.commit()
    db.refresh(experiment)
    db.refresh(version)
    return experiment, version


def transition_experiment_package(
    db: Session,
    actor: User,
    version: ExperimentVersion,
    target: str,
) -> ExperimentVersion:
    if target not in PACKAGE_TRANSITIONS.get(version.status, set()):
        raise ValueError(f"invalid package transition {version.status} -> {target}")
    report = PackageValidationReport.model_validate(version.validation_report)
    if target in {"approved", "published"} and not report.valid:
        raise ValueError("an invalid package cannot be approved or published")
    if target == "published":
        current = list(
            db.scalars(
                select(ExperimentVersion).where(
                    ExperimentVersion.experiment_id == version.experiment_id,
                    ExperimentVersion.is_current.is_(True),
                    ExperimentVersion.id != version.id,
                )
            )
        )
        for item in current:
            item.is_current = False
            if item.status == "published":
                item.status = "superseded"
        version.is_current = True
        version.published_at = utc_now()
    elif target in {"revoked", "superseded"}:
        version.is_current = False
    version.status = target
    version.reviewed_by_user_id = actor.id
    db.add(
        AuditEvent(
            actor_user_id=actor.id,
            action=f"experiment_package.{target}",
            resource_type="experiment_version",
            resource_id=version.id,
            details_json={"package_hash": version.package_hash},
            is_test_data=version.is_test_data,
            created_at=utc_now(),
        )
    )
    db.commit()
    db.refresh(version)
    return version


def load_experiment_package_runtime(
    db: Session,
    experiment_version_id: str,
    *,
    require_published: bool = True,
) -> ExperimentPackageRuntime:
    version = db.get(ExperimentVersion, experiment_version_id)
    if version is None:
        raise ExperimentPackageLoadError("experiment package version not found")
    if require_published and version.status not in RUNTIME_STATUSES:
        raise ExperimentPackageLoadError("experiment package version is not published")
    experiment = db.get(Experiment, version.experiment_id)
    if experiment is None:
        raise ExperimentPackageLoadError("experiment package identity not found")
    bundle, report = load_experiment_package_payload(version.package_content)
    if (
        report.package_hash != version.package_hash
        or bundle.manifest.model_dump(mode="json") != version.package_manifest
    ):
        raise ExperimentPackageLoadError("stored experiment package integrity check failed")
    return ExperimentPackageRuntime(
        experiment=experiment,
        version=version,
        bundle=bundle,
        definition=package_to_experiment_definition(bundle),
        rule_document=package_rule_document(bundle),
        fault_tree_document=package_fault_tree_document(bundle),
    )
