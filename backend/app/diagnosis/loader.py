import hashlib
import json
from pathlib import Path

import yaml

from app.diagnosis.schemas import RuleSet

DEFAULT_RULE_DIRECTORY = Path(__file__).parent / "rules"


def load_rules(rule_directory: Path = DEFAULT_RULE_DIRECTORY) -> tuple[RuleSet, str]:
    documents = []
    for path in sorted(rule_directory.glob("*.yaml")):
        with path.open(encoding="utf-8") as stream:
            documents.append(yaml.safe_load(stream))
    if not documents:
        raise ValueError(f"no YAML rules found in {rule_directory}")

    versions = {str(document.get("version")) for document in documents}
    if len(versions) != 1:
        raise ValueError("all rule files must use the same version")
    payload = {
        "version": versions.pop(),
        "rules": [rule for document in documents for rule in document.get("rules", [])],
    }
    ruleset = RuleSet.model_validate(payload)
    canonical = json.dumps(ruleset.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return ruleset, hashlib.sha256(canonical.encode()).hexdigest()
