from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.experiments.schemas import ExperimentDefinition

DEFAULT_EXPERIMENT_DIRECTORY = Path(__file__).parent / "definitions"


class ExperimentDefinitionLoadError(ValueError):
    """A definition is missing, ambiguous, malformed, or fails schema validation."""


def experiment_definition_hash(definition: ExperimentDefinition) -> str:
    canonical = json.dumps(
        definition.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_experiment_definitions(
    directory: Path = DEFAULT_EXPERIMENT_DIRECTORY,
) -> list[tuple[ExperimentDefinition, str]]:
    paths = sorted([*directory.rglob("*.yaml"), *directory.rglob("*.yml")])
    if not paths:
        raise ExperimentDefinitionLoadError(f"no experiment definitions found in {directory}")
    loaded: list[tuple[ExperimentDefinition, str]] = []
    identities: set[tuple[str, str]] = set()
    for path in paths:
        try:
            with path.open(encoding="utf-8") as stream:
                payload = yaml.safe_load(stream)
            if not isinstance(payload, dict):
                raise ExperimentDefinitionLoadError("document root must be an object")
            definition = ExperimentDefinition.model_validate(payload)
        except (OSError, yaml.YAMLError, ValidationError, ExperimentDefinitionLoadError) as exc:
            raise ExperimentDefinitionLoadError(
                f"invalid experiment definition {path}: {exc}"
            ) from exc
        identity = (definition.experiment.id, definition.experiment.version)
        if identity in identities:
            raise ExperimentDefinitionLoadError(
                f"duplicate experiment definition {identity[0]}@{identity[1]}"
            )
        identities.add(identity)
        loaded.append((definition, experiment_definition_hash(definition)))
    return loaded


def load_experiment_definition(
    experiment_id: str,
    version: str | None = None,
    directory: Path = DEFAULT_EXPERIMENT_DIRECTORY,
) -> tuple[ExperimentDefinition, str]:
    matches = [
        item
        for item in load_experiment_definitions(directory)
        if item[0].experiment.id == experiment_id
        and (version is None or item[0].experiment.version == version)
    ]
    if not matches:
        suffix = f"@{version}" if version else ""
        raise ExperimentDefinitionLoadError(
            f"experiment definition not found: {experiment_id}{suffix}"
        )
    if version is None and len(matches) > 1:
        available = ", ".join(sorted(item[0].experiment.version for item in matches))
        raise ExperimentDefinitionLoadError(
            f"experiment version is required for {experiment_id}; available: {available}"
        )
    return matches[0]
