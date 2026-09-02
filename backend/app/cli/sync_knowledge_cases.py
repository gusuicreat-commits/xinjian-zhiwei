"""Validate and synchronize external YAML knowledge cases into PostgreSQL."""

from app.db.session import SessionLocal
from app.knowledge.loader import load_case_definitions
from app.models.knowledge import KnowledgeCase


def main() -> None:
    definitions = load_case_definitions()
    with SessionLocal() as db:
        for item in definitions:
            values = item.model_dump(by_alias=False)
            case_id = values.pop("id")
            record = db.get(KnowledgeCase, case_id)
            if record is None:
                record = KnowledgeCase(id=case_id, **values)
                db.add(record)
            else:
                for key, value in values.items():
                    setattr(record, key, value)
        db.commit()
    print(f"synchronized {len(definitions)} structured knowledge cases")


if __name__ == "__main__":
    main()
