import hashlib
import json
from pathlib import Path

import yaml

from app.diagnosis.fault_tree_schemas import FaultTreeSet
from app.diagnosis.loader import _scope_matches, _source_id
from app.diagnosis.schemas import ArtifactScope, DiagnosisContext

DEFAULT_FAULT_TREE_DIRECTORY = Path(__file__).parent / "fault_trees"


def load_fault_trees(
    tree_directory: Path = DEFAULT_FAULT_TREE_DIRECTORY,
    *,
    context: DiagnosisContext | None = None,
) -> tuple[FaultTreeSet, str]:
    documents: list[tuple[Path, dict, str, ArtifactScope]] = []
    available_sources: set[str] = set()
    paths = sorted([*tree_directory.rglob("*.yaml"), *tree_directory.rglob("*.yml")])
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            document = yaml.safe_load(stream)
        if not isinstance(document, dict):
            raise ValueError(f"fault-tree document root must be an object: {path}")
        source_id = _source_id(path, tree_directory, document)
        if source_id in available_sources:
            raise ValueError(f"fault-tree source_id must be unique: {source_id}")
        available_sources.add(source_id)
        scope = ArtifactScope.model_validate(document.get("scope") or {})
        if context is None:
            if path.parent != tree_directory:
                continue
        elif context.artifact_selection.fault_tree_sources:
            if source_id not in context.artifact_selection.fault_tree_sources:
                continue
            if not _scope_matches(scope, context):
                raise ValueError(
                    f"fault-tree source {source_id} is outside experiment "
                    f"{context.experiment_id} scope"
                )
        elif not _scope_matches(scope, context):
            continue
        documents.append((path, document, source_id, scope))
    if context is not None and context.artifact_selection.fault_tree_sources:
        missing = set(context.artifact_selection.fault_tree_sources) - available_sources
        if missing:
            raise ValueError(f"configured fault-tree sources were not loaded: {sorted(missing)}")
    if not documents:
        raise ValueError(f"no YAML fault trees found in {tree_directory}")
    versions = {str(document.get("version")) for _, document, _, _ in documents}
    if len(versions) != 1:
        raise ValueError("all fault tree files must use the same version")
    payload = {
        "version": versions.pop(),
        "source_versions": {
            source_id: str(document.get("version")) for _, document, source_id, _ in documents
        },
        "trees": [
            {
                **tree,
                "source_id": source_id,
                "source_path": str(path.relative_to(tree_directory)),
                "source_version": str(document.get("version")),
                "scope": scope.model_dump(mode="json"),
            }
            for path, document, source_id, scope in documents
            for tree in document.get("trees", [])
        ],
    }
    tree_set = FaultTreeSet.model_validate(payload)
    canonical = json.dumps(tree_set.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return tree_set, hashlib.sha256(canonical.encode()).hexdigest()


def load_fault_trees_from_document(
    document: dict,
    *,
    context: DiagnosisContext,
) -> tuple[FaultTreeSet, str]:
    """Compile one immutable experiment-package fault-tree document."""

    source_id = str(document.get("source_id") or "package.fault_tree")
    scope = ArtifactScope.model_validate(document.get("scope") or {})
    if not _scope_matches(scope, context):
        raise ValueError(
            f"package fault-tree source {source_id} is outside experiment "
            f"{context.experiment_id} scope"
        )
    version = str(document.get("version") or "")
    payload = {
        "version": version,
        "source_versions": {source_id: version},
        "trees": [
            {
                **tree,
                "source_id": source_id,
                "source_path": "experiment_package/diagnosis/fault_tree.yaml",
                "source_version": version,
                "scope": scope.model_dump(mode="json"),
            }
            for tree in document.get("trees", [])
        ],
    }
    tree_set = FaultTreeSet.model_validate(payload)
    canonical = json.dumps(tree_set.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return tree_set, hashlib.sha256(canonical.encode()).hexdigest()
