import hashlib
import json
from pathlib import Path

import yaml

from app.diagnosis.schemas import ArtifactScope, DiagnosisContext, RuleSet

DEFAULT_RULE_DIRECTORY = Path(__file__).parent / "rules"


def _source_id(path: Path, root: Path, document: dict) -> str:
    relative = path.relative_to(root).with_suffix("")
    return str(document.get("source_id") or ".".join(relative.parts))


def _scope_matches(scope: ArtifactScope, context: DiagnosisContext) -> bool:
    if scope.kind == "common":
        return True
    if scope.kind == "experiment":
        return context.experiment_id is not None and context.experiment_id in scope.keys
    if scope.kind == "interface":
        values = {item.id for item in context.interfaces} | {
            item.type for item in context.interfaces
        }
        return bool(values & set(scope.keys))
    values = (
        {item.id for item in context.components}
        | {item.kind for item in context.components}
        | {item.model for item in context.components if item.model}
    )
    return bool(values & set(scope.keys))


def load_rules(
    rule_directory: Path = DEFAULT_RULE_DIRECTORY,
    *,
    context: DiagnosisContext | None = None,
) -> tuple[RuleSet, str]:
    documents: list[tuple[Path, dict, str, ArtifactScope]] = []
    available_sources: set[str] = set()
    paths = sorted([*rule_directory.rglob("*.yaml"), *rule_directory.rglob("*.yml")])
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            document = yaml.safe_load(stream)
        if not isinstance(document, dict):
            raise ValueError(f"rule document root must be an object: {path}")
        source_id = _source_id(path, rule_directory, document)
        if source_id in available_sources:
            raise ValueError(f"rule source_id must be unique: {source_id}")
        available_sources.add(source_id)
        scope = ArtifactScope.model_validate(document.get("scope") or {})
        if context is None:
            if path.parent != rule_directory:
                continue
        elif context.artifact_selection.rule_sources:
            if source_id not in context.artifact_selection.rule_sources:
                continue
            if not _scope_matches(scope, context):
                raise ValueError(
                    f"rule source {source_id} is outside experiment {context.experiment_id} scope"
                )
        elif not _scope_matches(scope, context):
            continue
        documents.append((path, document, source_id, scope))
    if context is not None and context.artifact_selection.rule_sources:
        missing = set(context.artifact_selection.rule_sources) - available_sources
        if missing:
            raise ValueError(f"configured rule sources were not loaded: {sorted(missing)}")
    if not documents:
        raise ValueError(f"no YAML rules found in {rule_directory}")

    versions = {str(document.get("version")) for _, document, _, _ in documents}
    if len(versions) != 1:
        raise ValueError("all rule files must use the same version")
    payload = {
        "version": versions.pop(),
        "source_versions": {
            source_id: str(document.get("version")) for _, document, source_id, _ in documents
        },
        "rules": [
            {
                **rule,
                "source_id": source_id,
                "source_path": str(path.relative_to(rule_directory)),
                "source_version": str(document.get("version")),
                "scope": scope.model_dump(mode="json"),
            }
            for path, document, source_id, scope in documents
            for rule in document.get("rules", [])
        ],
    }
    ruleset = RuleSet.model_validate(payload)
    canonical = json.dumps(ruleset.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return ruleset, hashlib.sha256(canonical.encode()).hexdigest()
