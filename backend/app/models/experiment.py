from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin


class Experiment(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Stable identity shared by all immutable package versions."""

    __tablename__ = "experiments"

    code: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), default="zh-CN", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ExperimentVersion(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable validated Experiment Package snapshot."""

    __tablename__ = "experiment_versions"
    __table_args__ = (
        UniqueConstraint("experiment_id", "version", name="uq_experiment_versions_pair"),
        UniqueConstraint("id", "experiment_id", name="uq_experiment_versions_id_experiment"),
        Index("ix_experiment_versions_status_published", "status", "published_at"),
    )

    experiment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("experiments.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    engine_compatibility: Mapped[str] = mapped_column(String(100), nullable=False)
    package_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    package_manifest: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    package_content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    validation_report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reviewed_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ExperimentPackageArtifact(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Queryable artifact index backed by the immutable package snapshot."""

    __tablename__ = "experiment_package_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "experiment_version_id",
            "kind",
            "artifact_key",
            name="uq_experiment_package_artifact",
        ),
        Index("ix_experiment_package_artifacts_version_kind", "experiment_version_id", "kind"),
    )

    experiment_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("experiment_versions.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    artifact_key: Mapped[str] = mapped_column(String(200), nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)


class ExperimentTemplate(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "experiment_templates"

    code: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ExperimentTemplateVersion(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "experiment_template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version", name="uq_template_versions_pair"),)

    template_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("experiment_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column("content", JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    missing_fields_json: Mapped[list[str]] = mapped_column(
        "missing_fields", JSON, default=list, nullable=False
    )
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reviewed_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class DiagnosticArtifact(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "diagnostic_artifacts"
    __table_args__ = (
        UniqueConstraint("kind", "code", "version", name="uq_diagnostic_artifact_version"),
    )

    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    definition_json: Mapped[dict[str, Any]] = mapped_column("definition", JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
