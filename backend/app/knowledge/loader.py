from __future__ import annotations

from pathlib import Path

import yaml

from app.schemas.knowledge_case import KnowledgeCaseDefinition


def default_knowledge_root() -> Path:
    package_relative = Path(__file__).resolve().parents[2] / "knowledge"
    if (package_relative / "cases").is_dir():
        return package_relative
    runtime_relative = Path.cwd() / "knowledge"
    if (runtime_relative / "cases").is_dir():
        return runtime_relative
    return package_relative


def load_case_definitions(root: Path | None = None) -> list[KnowledgeCaseDefinition]:
    cases_dir = (root or default_knowledge_root()) / "cases"
    definitions: list[KnowledgeCaseDefinition] = []
    seen_ids: set[str] = set()
    for path in sorted(cases_dir.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for raw in payload.get("cases", []):
            case = KnowledgeCaseDefinition.model_validate(raw)
            if case.id in seen_ids:
                raise ValueError(f"duplicate knowledge case id: {case.id}")
            seen_ids.add(case.id)
            definitions.append(case)
    return definitions
