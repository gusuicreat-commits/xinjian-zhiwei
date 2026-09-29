"""Strict material registration and pure identity checks; never reads external sources."""

import hashlib
import json
from typing import Any, Literal

from pydantic import Field, model_validator

from app.diagnosis.schemas import StrictModel
from app.schemas.knowledge_case import CaseApplicabilityConditions

IDENTITY = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
HASH = r"^[a-f0-9]{64}$"


class MaterialSource(StrictModel):
    source_id: str = Field(pattern=IDENTITY, max_length=100)
    kind: Literal[
        "project_design",
        "vendor_document",
        "course_material",
        "experiment_record",
        "code",
        "internal_document",
    ]
    revision: str | None = Field(default=None, max_length=200)
    location: str = Field(min_length=1, max_length=500)
    locator: str | None = Field(default=None, max_length=500)
    availability: Literal["available", "pending"]
    sha256: str | None = Field(default=None, pattern=HASH)


class MaterialSelector(StrictModel):
    artifact: Literal[
        "hardware.yaml",
        "diagnosis/rules.yaml",
        "diagnosis/fault_tree.yaml",
        "knowledge/concepts.yaml",
        "knowledge/cases.yaml",
        "teaching/steps.yaml",
    ]
    entity_kind: Literal[
        "interface",
        "component",
        "required_parameters",
        "runtime_expectations",
        "rule",
        "fault_tree",
        "concept",
        "case",
        "step",
    ]
    entity_id: str | None = Field(default=None, pattern=IDENTITY, max_length=100)
    field: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){0,2}$", max_length=100
    )


class MaterialSourceReference(StrictModel):
    source_id: str = Field(pattern=IDENTITY, max_length=100)
    claim: str = Field(min_length=1, max_length=300)
    locator: str = Field(min_length=1, max_length=500)


class MaterialDerivation(StrictModel):
    kind: Literal["case", "package_unit"]
    id: str = Field(pattern=IDENTITY, max_length=100)
    version: str = Field(min_length=1, max_length=100)
    hash: str = Field(pattern=HASH)
    package_id: str | None = Field(default=None, min_length=1, max_length=100)
    relation: Literal["snapshot", "adapted"]

    @model_validator(mode="after")
    def package_identity(self):
        if (self.kind == "package_unit") != bool(self.package_id):
            raise ValueError("package derivation requires exactly its package identity")
        return self


class MaterialApplicability(StrictModel):
    limits_text: str = Field(min_length=1, max_length=2000)
    applicability_conditions: CaseApplicabilityConditions | None = None

    @model_validator(mode="after")
    def nonempty_limits(self):
        if not self.limits_text.strip():
            raise ValueError("material limits must not be blank")
        return self


class MaterialUnit(StrictModel):
    unit_id: str = Field(pattern=IDENTITY, max_length=100)
    target: MaterialSelector
    statement_kind: Literal[
        "source_claim", "project_configuration", "observed_result", "pending_proposal"
    ]
    source_refs: list[MaterialSourceReference] = Field(default_factory=list, max_length=30)
    derived_from: list[MaterialDerivation] = Field(default_factory=list, max_length=30)
    depends_on: list[str] = Field(default_factory=list, max_length=30)
    applicability: MaterialApplicability | None = None

    @model_validator(mode="after")
    def limits_owner(self):
        if self.target.entity_kind in {"concept", "step", "case"} and self.target.field is not None:
            raise ValueError("case, concept and step units must retain the complete entity")
        if self.applicability is not None and self.target.entity_kind not in {"concept", "step"}:
            raise ValueError("only concept and step units own registry applicability")
        return self


class MaterialValue(StrictModel):
    target: MaterialSelector
    unit: str = Field(min_length=1, max_length=50)


class ValueOwner(StrictModel):
    parameter_id: str = Field(pattern=IDENTITY, max_length=100)
    owner: MaterialValue
    copies: list[MaterialValue] = Field(default_factory=list, max_length=30)


class ContentRegistry(StrictModel):
    sources: list[MaterialSource] = Field(default_factory=list, max_length=200)
    units: list[MaterialUnit] = Field(default_factory=list, max_length=500)
    value_owners: list[ValueOwner] = Field(default_factory=list, max_length=100)


def content_digest(value: Any) -> str:
    """Same canonical JSON identity as the package manifest, without I/O."""
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def derivation_key(source: MaterialDerivation) -> str:
    """Stable caller key for explicitly supplied trusted derivation bytes/JSON."""
    return ":".join(filter(None, (source.kind, source.package_id, source.id, source.version)))


def _dump(value):
    return value.model_dump(mode="json", by_alias=True) if hasattr(value, "model_dump") else value


def resolve_selector(bundle, selector: MaterialSelector):
    """Resolve only registered entities and fields, never filesystem or expressions."""
    kinds = {
        "interface": ("hardware.yaml", bundle.hardware.interfaces, "id"),
        "component": ("hardware.yaml", bundle.hardware.hardware.components, "id"),
        "rule": ("diagnosis/rules.yaml", bundle.rules.rules, "id"),
        "fault_tree": ("diagnosis/fault_tree.yaml", bundle.fault_trees.trees, "id"),
        "concept": ("knowledge/concepts.yaml", bundle.concepts.concepts, "concept_id"),
        "case": ("knowledge/cases.yaml", bundle.cases.cases, "id"),
        "step": ("teaching/steps.yaml", bundle.steps.steps, "step_id"),
    }
    if selector.entity_kind in {"required_parameters", "runtime_expectations"}:
        if selector.artifact != "hardware.yaml" or selector.entity_id is not None:
            raise ValueError("invalid singleton selector")
        value = _dump(getattr(bundle.hardware, selector.entity_kind))
    else:
        artifact, rows, id_field = kinds[selector.entity_kind]
        matching = [row for row in rows if getattr(row, id_field) == selector.entity_id]
        if selector.artifact != artifact or len(matching) != 1:
            raise ValueError("material selector must identify one declared entity")
        value = _dump(matching[0])
    if value is None:
        raise ValueError("material selector target is unavailable")
    if selector.field is None:
        return value
    fields = {
        "concept": {"description"},
        "step": {"title", "expected_state"},
        "case": {"symptom"},
        "component": {"model", "kind"},
        "required_parameters": {
            "data_pin",
            "output_pin",
            "active_level",
            "minimum_interval_ms",
            "consecutive_failure_threshold",
        },
        "runtime_expectations": {"offline_after_seconds", "heartbeat_maximum_age_seconds"},
        "interface": {
            "pins.data",
            "pins.output",
            "parameters.minimum_interval_ms",
            "parameters.configured_sample_interval_ms",
            "parameters.active_level",
        },
        "rule": {"priority"},
        "fault_tree": set(),
    }
    if selector.field not in fields[selector.entity_kind]:
        raise ValueError("material selector field is not registered")
    for key in selector.field.split("."):
        if not isinstance(value, dict) or key not in value:
            raise ValueError("material selector field is missing")
        value = value[key]
    return value


def resolve_unit(bundle, unit):
    if isinstance(unit, str):
        registry = getattr(bundle.metadata, "content_registry", None)
        matches = [item for item in registry.units if item.unit_id == unit] if registry else []
        if len(matches) != 1:
            raise ValueError("unknown material unit")
        unit = matches[0]
    return resolve_selector(bundle, unit.target)


def _unique(items, label):
    if len(items) != len(set(items)):
        raise ValueError(f"duplicate registry {label}")


def _trusted_digest(value):
    return hashlib.sha256(value).hexdigest() if isinstance(value, bytes) else content_digest(value)


def _identity_payload(bundle, unit, sources, dependencies):
    return {
        "target": _dump(unit.target),
        "body": resolve_unit(bundle, unit),
        "statement_kind": unit.statement_kind,
        "applicability": _dump(unit.applicability),
        "source_refs": [_dump(ref) for ref in unit.source_refs],
        "sources": [_dump(sources[ref.source_id]) for ref in unit.source_refs],
        "derived_from": [_dump(origin) for origin in unit.derived_from],
        "dependencies": dependencies,
    }


def unit_identity_payload(bundle, unit_id):
    """Export an explicitly authorized unit snapshot for a later provenance check.

    Includes the source material, so callers must not publish this as a preview
    report or Provider input. No external source is fetched by this function.
    """
    report = registry_report(bundle)
    registry = getattr(bundle.metadata, "content_registry", None)
    units = {unit.unit_id: unit for unit in registry.units} if registry else {}
    if unit_id not in units:
        raise ValueError("unknown material unit")
    unit = units[unit_id]
    hashes = {item["unit_id"]: item["unit_hash"] for item in report["units"]}
    return _identity_payload(
        bundle,
        unit,
        {s.source_id: s for s in registry.sources},
        {dep: hashes[dep] for dep in unit.depends_on},
    )


def registry_report(bundle, *, package_version_id="offline:unbound", trusted_sources=None):
    """Return deterministic unit identities and traceability; caller supplies trusted bytes/JSON.

    trusted_sources maps source_id or derivation_key(...) to a trusted source snapshot.
    An absent snapshot is unverifiable, never implicitly fetched or approved.
    """
    registry = getattr(bundle.metadata, "content_registry", None)
    if registry is None:
        return {
            "schema_version": "1.0",
            "source_traceability": "not_provided",
            "sources": [],
            "units": [],
        }
    trusted_sources = trusted_sources or {}
    _unique([s.source_id for s in registry.sources], "source IDs")
    _unique([u.unit_id for u in registry.units], "unit IDs")
    _unique([content_digest(_dump(u.target)) for u in registry.units], "unit targets")
    _unique([v.parameter_id for v in registry.value_owners], "parameter IDs")
    _unique(
        [
            content_digest(_dump(item.target))
            for entry in registry.value_owners
            for item in [entry.owner, *entry.copies]
        ],
        "parameter field ownership",
    )
    sources = {source.source_id: source for source in registry.sources}
    units = {unit.unit_id: unit for unit in registry.units}
    identities, source_results = {}, []
    for source in registry.sources:
        supplied = trusted_sources.get(source.source_id)
        status = "unverifiable"
        if supplied is not None and source.sha256 is not None:
            if _trusted_digest(supplied) != source.sha256:
                raise ValueError("source snapshot hash mismatch")
            status = "verified_identity"
        source_results.append({"source_id": source.source_id, "status": status})

    def identify(key):
        unit = units[key]
        _unique(unit.depends_on, "dependencies")
        if any(ref.source_id not in sources for ref in unit.source_refs):
            raise ValueError("missing registry source reference")
        dependencies = {dep: identities[dep] for dep in unit.depends_on}
        derivations = []
        for origin in unit.derived_from:
            if origin.package_id == package_version_id:
                raise ValueError("current-package dependencies must use local unit identities")
            supplied = trusted_sources.get(derivation_key(origin))
            status = "unverifiable"
            if supplied is not None:
                if _trusted_digest(supplied) != origin.hash:
                    raise ValueError("derived source hash mismatch")
                status = "verified_identity"
            derivations.append({"source": _dump(origin), "status": status})
        identities[key] = content_digest(_identity_payload(bundle, unit, sources, dependencies))
        unit_results[key] = {
            "unit_id": key,
            "unit_hash": identities[key],
            "package_version_id": package_version_id,
            "package_hash": bundle.manifest.package_hash,
            "target": _dump(unit.target),
            "depends_on": list(unit.depends_on),
            "source_refs": [_dump(ref) for ref in unit.source_refs],
            "derivations": derivations,
            "review_status": "not_evaluated",
        }
        return identities[key]

    unit_results = {}
    if any(dep not in units for unit in registry.units for dep in unit.depends_on):
        raise ValueError("missing material dependency")
    pending = list(units)
    while pending:
        ready = [key for key in pending if all(dep in identities for dep in units[key].depends_on)]
        if not ready:
            raise ValueError("cyclic material dependency")
        for key in ready:
            identify(key)
            pending.remove(key)
    for parameter in registry.value_owners:
        entries = [parameter.owner, *parameter.copies]
        _unique([content_digest(_dump(item.target)) for item in entries], "parameter fields")
        if any(item.target.field is None for item in entries):
            raise ValueError("parameter selector must identify a scalar field")
        value = resolve_selector(bundle, parameter.owner.target)
        if isinstance(value, (dict, list)):
            raise ValueError("parameter value must be scalar")
        for copy in parameter.copies:
            other = resolve_selector(bundle, copy.target)
            if (
                copy.unit != parameter.owner.unit
                or type(other) is not type(value)
                or other != value
            ):
                raise ValueError("registered parameter value or unit mismatch")
    statuses = [item["status"] for item in source_results]
    statuses.extend(d["status"] for item in unit_results.values() for d in item["derivations"])
    complete = bool(statuses) and all(status == "verified_identity" for status in statuses)
    if any(not unit.source_refs and not unit.derived_from for unit in registry.units):
        complete = False
    return {
        "schema_version": "1.1",
        "source_traceability": "verified_identity" if complete else "unverifiable",
        "sources": source_results,
        "units": [unit_results[u.unit_id] for u in registry.units],
    }


def validate_registry(bundle, *, trusted_sources=None):
    """Raise ValueError on invalid registration; unavailable evidence remains explicit."""
    registry_report(bundle, trusted_sources=trusted_sources)
    for case in bundle.cases.cases:
        material = case.solution_record.get("confirmation_material")
        if isinstance(material, dict) and "applicability_conditions" in material:
            if bundle.metadata.schema_version != "1.1":
                raise ValueError("structured applicability conditions require package schema 1.1")
            if material["applicability_conditions"] is not None:
                CaseApplicabilityConditions.model_validate(material["applicability_conditions"])


def derived_case_matches(documents, source):
    """Known source identity yields impact candidates only, never automatic revocation."""
    metadata = documents.get("metadata.yaml") or {}
    if metadata.get("schema_version") != "1.1" or source.get("kind") != "case":
        return False
    registry = ContentRegistry.model_validate(metadata.get("content_registry"))
    return any(
        origin.kind == "case"
        and origin.id == source.get("id")
        and origin.version == source.get("version")
        and origin.hash == source.get("hash")
        for unit in registry.units
        for origin in unit.derived_from
    )
