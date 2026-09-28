"""Validate and insert external YAML cases without rewriting existing history."""

from sqlalchemy import select

from app.db.session import SessionLocal
from app.knowledge.loader import load_case_definitions
from app.models.knowledge import KnowledgeCase
from app.services.memory import digest


def sync_case_definitions(db, definitions):
    pending = []
    for item in sorted(definitions, key=lambda value: value.id):
        values = item.model_dump(by_alias=False)
        case_id = values.pop("id")
        record = db.scalar(
            select(KnowledgeCase)
            .where(KnowledgeCase.id == case_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if record is None:
            pending.append(KnowledgeCase(id=case_id, **values))
        elif digest({key: getattr(record, key) for key in values}) != digest(values):
            raise ValueError(
                "existing structured cases are immutable; use a new case ID or package version"
            )
    db.add_all(pending)
    db.commit()
    return len(pending)


def main() -> None:
    definitions = load_case_definitions()
    with SessionLocal() as db:
        count = sync_case_definitions(db, definitions)
    print(f"inserted {count} structured cases; existing content was preserved")


if __name__ == "__main__":
    main()
