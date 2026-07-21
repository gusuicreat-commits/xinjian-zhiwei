from __future__ import annotations

from typing import Any

from sqlalchemy.types import TypeDecorator, UserDefinedType


class _PostgresVector(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **_: Any) -> str:
        return "VECTOR"

    def bind_processor(self, dialect: Any):
        def process(value: list[float] | None) -> str | None:
            if value is None:
                return None
            return "[" + ",".join(format(float(item), ".12g") for item in value) + "]"

        return process

    def result_processor(self, dialect: Any, coltype: Any):
        def process(value: Any) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, list):
                return [float(item) for item in value]
            text = str(value).strip().strip("[]")
            return [] if not text else [float(item) for item in text.split(",")]

        return process


class PortableVector(TypeDecorator[list[float]]):
    """Use pgvector on PostgreSQL and JSON in the SQLite test database."""

    impl = _PostgresVector
    cache_ok = True

    def load_dialect_impl(self, dialect: Any):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PostgresVector())
        from sqlalchemy import JSON

        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: list[float] | None, dialect: Any) -> list[float] | None:
        if value is None:
            return None
        return [float(item) for item in value]

    def process_result_value(
        self, value: list[float] | str | None, dialect: Any
    ) -> list[float] | None:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip().strip("[]")
            return [] if not text else [float(item) for item in text.split(",")]
        return [float(item) for item in value]
