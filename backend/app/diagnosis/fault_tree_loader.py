import hashlib
import json
from pathlib import Path

import yaml

from app.diagnosis.fault_tree_schemas import FaultTreeSet

DEFAULT_FAULT_TREE_DIRECTORY = Path(__file__).parent / "fault_trees"


def load_fault_trees(
    tree_directory: Path = DEFAULT_FAULT_TREE_DIRECTORY,
) -> tuple[FaultTreeSet, str]:
    documents = []
    for path in sorted(tree_directory.glob("*.yaml")):
        with path.open(encoding="utf-8") as stream:
            documents.append(yaml.safe_load(stream))
    if not documents:
        raise ValueError(f"no YAML fault trees found in {tree_directory}")
    versions = {str(document.get("version")) for document in documents}
    if len(versions) != 1:
        raise ValueError("all fault tree files must use the same version")
    payload = {
        "version": versions.pop(),
        "trees": [tree for document in documents for tree in document.get("trees", [])],
    }
    tree_set = FaultTreeSet.model_validate(payload)
    canonical = json.dumps(tree_set.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return tree_set, hashlib.sha256(canonical.encode()).hexdigest()
