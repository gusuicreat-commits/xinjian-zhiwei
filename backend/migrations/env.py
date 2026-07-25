from logging.config import fileConfig
from typing import Optional

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.db.base import Base
from app.models import (  # noqa: F401
    AICallRecord,
    AIExplanationCache,
    Device,
    DeviceHeartbeat,
    DeviceLog,
    DiagnosisEpisode,
    DiagnosisFeedback,
    DiagnosisResult,
    GuidanceHistory,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEmbedding,
    KnowledgeReview,
    KnowledgeSource,
    SensorReading,
)

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(
    object_: object,
    name: Optional[str],
    type_: str,
    reflected: bool,
    compare_to: Optional[object],
) -> bool:
    del object_, reflected, compare_to
    # PostgreSQL-only expression index is intentionally managed by migration 0007.
    return not (type_ == "index" and name == "ix_knowledge_chunks_fts_simple")


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
