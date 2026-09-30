
"""Attach deterministic, versioned reference material to existing guidance hints.

References are not actions or observed facts and are deliberately excluded from
Provider inputs. Old guidance is never enriched retroactively.
"""

from copy import deepcopy

from app.experiment_packages.loader import ExperimentPackageLoadError
from app.experiment_packages.teaching import ordered_steps
from app.services.experiment_packages import load_experiment_package_runtime
from app.services.provenance import derive_test_flag


def select_teaching_materials(bundle, *, tree_id, cause_id, level, scope):
    empty = {"concepts": [], "steps": []}
    # Ambiguous or interface-wide ownership cannot authorize component-specific text.
    if scope.get("kind") != "component" or len(scope.get("keys", [])) != 1:
        return empty
    binding = next(
        (
            b
            for b in bundle.steps.bindings
            if b.tree_id == tree_id
            and b.cause_id == cause_id
            and b.component_id == scope["keys"][0]
            and level in b.levels
        ),
        None,
    )
    if binding is None:
        return empty
    by_id = {c.concept_id: c for c in bundle.concepts.concepts}
    return {
        "concepts": [by_id[key].model_dump(mode="json") for key in binding.concept_ids],
        "steps": [
            step.model_dump(mode="json")
            for step in ordered_steps(bundle.steps.steps, binding.step_ids)
        ],
    }


def attach_teaching_materials(db, diagnosis, *, tree_id, scope, hints):
    """Called only while creating new guidance, before its existing atomic commit."""
    result = deepcopy(hints)
    base = {
        "contract_version": "teaching-reference-v1",
        "status": "missing",
        "experiment_version_id": diagnosis.experiment_version_id,
        "package_version": None,
        "package_hash": None,
        "is_test_data": diagnosis.is_test_data,
        "concepts": [],
        "steps": [],
    }
    runtime = None
    if diagnosis.experiment_version_id:
        try:
            runtime = load_experiment_package_runtime(db, diagnosis.experiment_version_id)
            expected_hash = diagnosis.context_snapshot.get("experiment_package_hash")
            if not expected_hash or expected_hash != runtime.version.package_hash:
                raise ExperimentPackageLoadError("diagnosis package identity mismatch")
            base.update(
                package_version=runtime.version.version,
                package_hash=runtime.version.package_hash,
                is_test_data=derive_test_flag(diagnosis.is_test_data, runtime.version.is_test_data),
            )
        except ExperimentPackageLoadError:
            runtime = None
            base["status"] = "unavailable"
    for hint in result:
        snapshot = deepcopy(base)
        if runtime is not None:
            snapshot.update(
                select_teaching_materials(
                    runtime.bundle,
                    tree_id=tree_id,
                    cause_id=hint["cause_id"],
                    level=hint["level"],
                    scope=scope or {},
                )
            )
            if snapshot["concepts"] or snapshot["steps"]:
                snapshot["status"] = "available"
        hint["teaching"] = snapshot
    return result
