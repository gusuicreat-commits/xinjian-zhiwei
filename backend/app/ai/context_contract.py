"""Internal context audit types. Never part of a Provider or public API schema."""

from dataclasses import dataclass, field
from typing import Any

CONTEXT_CONTRACT_VERSION = "context-manifest-v1"
CONTEXT_POLICY_VERSION = "whole-unit-v1"


@dataclass
class ContextManifestV1:
    stage: str
    contract_version: str = CONTEXT_CONTRACT_VERSION
    policy_version: str = CONTEXT_POLICY_VERSION
    prepared_source_refs: list[dict[str, Any]] = field(default_factory=list)
    provider_attempted: bool = False
    submitted_source_refs: list[dict[str, Any]] = field(default_factory=list)
    cache_origin: str | None = None
    selected_ids: dict[str, list[str]] = field(default_factory=dict)
    omission_counts: dict[str, int] = field(default_factory=dict)
    required_complete: bool = True
    reason_codes: list[str] = field(default_factory=list)
    payload_sha256: str | None = None
    prompt_hash: str | None = None
    budget: dict[str, int] = field(default_factory=dict)


@dataclass
class PreparedContext:
    payload: dict[str, Any]
    selected_references: list[Any]
    manifest: ContextManifestV1
