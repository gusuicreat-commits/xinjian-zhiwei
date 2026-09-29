"""Read-only package context rehearsal using the production matching and packing code.

Fixtures describe synthetic observations. Independent expectations are consumed only
by ``check_expectations`` after both stage builders have completed. No session,
Provider, publication, or package mutation is part of this module.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.ai.context_builder import (
    CONSTRAINT_CASE_FIELDS,
    payload_digest,
    prepare_explanation,
    seal_context,
)
from app.ai.context_contract import CONTEXT_CONTRACT_VERSION, CONTEXT_POLICY_VERSION
from app.ai.context_sanitizer import ProviderInputError, build_safe_ai_input
from app.ai.reasoning import REASONING_PROMPT_VERSION, _reasoning_prompt
from app.core.config import Settings
from app.experiment_packages.loader import PACKAGE_FILES, load_experiment_package
from app.knowledge.matcher import match_case_candidates
from app.knowledge.projection import case_references
from app.knowledge.validation import build_reasoning_knowledge_constraints
from app.schemas.knowledge_case import KnowledgeCaseDefinition

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "evaluation/package_context_inputs.json"
EXPECTATIONS = ROOT / "evaluation/package_context_expectations.json"
BUDGET_FIELDS = (
    "ai_knowledge_limit",
    "ai_knowledge_content_max_chars",
    "ai_input_token_limit",
    "ai_max_context_items",
    "ai_max_log_items",
)


class PreviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreviewEvidence(PreviewModel):
    id: str = Field(min_length=1, max_length=100)
    fact: str = Field(min_length=1)
    source: Literal["synthetic_fixture"] = "synthetic_fixture"
    status: Literal["observed", "unknown", "invalid"] = "observed"


class PreviewCandidate(PreviewModel):
    cause_id: str
    evidence_refs: list[str]
    score: float = Field(default=0.5, ge=0, le=1)


class PreviewAction(PreviewModel):
    cause_id: str
    hint_level: Literal[1, 2, 3, 4] = 1


class PreviewScenario(PreviewModel):
    id: str = Field(pattern=r"^[a-z0-9_.-]+$")
    mode: Literal["offline_fixture"]
    package: str = Field(min_length=1)
    source_mode: Literal["package", "controlled_test"] = "package"
    fixture_cases: list[KnowledgeCaseDefinition] = Field(default_factory=list)
    error_type: str
    component_ids: list[str] | None = None
    candidates: list[PreviewCandidate]
    evidence: list[PreviewEvidence]
    allowed_actions: list[PreviewAction]
    stages: list[Literal["reasoning", "explanation"]] = Field(
        default_factory=lambda: ["reasoning", "explanation"], min_length=1, max_length=2
    )
    budgets: dict[str, StrictInt] = Field(default_factory=dict)

    @model_validator(mode="after")
    def input_contract(self):
        if len(set(self.stages)) != len(self.stages):
            raise ValueError("duplicate stage")
        if set(self.budgets) - set(BUDGET_FIELDS):
            raise ValueError("unsupported budget field")
        if self.source_mode == "package" and self.fixture_cases:
            raise ValueError("package sources cannot be replaced by fixture cases")
        if self.source_mode == "controlled_test" and not self.fixture_cases:
            raise ValueError("controlled_test requires independent case fixtures")
        if any(
            not case.is_test_data or case.source_type != "controlled_test"
            for case in self.fixture_cases
        ):
            raise ValueError("every fixture must be explicitly synthetic controlled_test")
        if len({item.id for item in self.fixture_cases}) != len(self.fixture_cases):
            raise ValueError("duplicate fixture case")
        if len({item.id for item in self.evidence}) != len(self.evidence):
            raise ValueError("duplicate evidence")
        if len({item.cause_id for item in self.candidates}) != len(self.candidates):
            raise ValueError("duplicate candidate")
        return self


class PreviewInputs(PreviewModel):
    schema_version: Literal["package-context-inputs-v1"]
    cases: list[PreviewScenario] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("duplicate scenario")
        return self


def preview_settings(overrides: dict[str, int]) -> Settings:
    """Freeze explicit project defaults; process env cannot silently change budgets."""
    if set(overrides) - set(BUDGET_FIELDS):
        raise ValueError("unsupported budget field")
    if any(type(value) is not int for value in overrides.values()):
        raise ValueError("budget values must be integers")
    values = {key: Settings.model_fields[key].default for key in BUDGET_FIELDS}
    values.update(overrides)
    return Settings(
        _env_file=None,
        **values,
        ai_enabled=False,
        ai_local_enabled=False,
        ai_cloud_enabled=False,
        ai_require_knowledge=True,
        ai_prompt_version=Settings.model_fields["ai_prompt_version"].default,
        ai_output_language=Settings.model_fields["ai_output_language"].default,
    )


def _scenario_state(bundle, scenario):
    """Adapt explicit synthetic observations, never a package test's expected answer."""
    metadata = bundle.metadata
    offline_id = f"offline:{bundle.manifest.package_hash[:24]}"
    causes = {cause.id: cause for tree in bundle.fault_trees.trees for cause in tree.causes}
    if scenario.error_type not in {rule.error_type for rule in bundle.rules.rules}:
        raise ValueError("scenario error type is not in package rules")
    if any(
        item.cause_id not in causes for item in [*scenario.candidates, *scenario.allowed_actions]
    ):
        raise ValueError("scenario candidate/action is not in package fault tree")
    components = {item.id for item in bundle.hardware.hardware.components}
    if scenario.component_ids is not None and not set(scenario.component_ids) <= components:
        raise ValueError("scenario component is not in package hardware")
    candidates = [
        {
            "cause_id": item.cause_id,
            "name": causes[item.cause_id].title,
            "score": item.score,
            "evidence_refs": item.evidence_refs,
        }
        for item in scenario.candidates
    ]
    actions = [
        {
            "action_id": f"offline-action:{index}",
            "text": causes[item.cause_id].hints[item.hint_level],
        }
        for index, item in enumerate(scenario.allowed_actions)
    ]
    scope = (
        {"kind": "component", "keys": scenario.component_ids}
        if scenario.component_ids
        else {"kind": "experiment", "keys": [metadata.experiment.code]}
    )
    hints = [
        {"cause_id": item.cause_id, "level": item.hint_level, "text": action["text"]}
        for item, action in zip(scenario.allowed_actions, actions, strict=True)
    ]
    guidance = [
        SimpleNamespace(
            fault_tree_id="offline-tree",
            fault_tree_status="placeholder",
            hint_level=1,
            teacher_intervention_required=False,
            fault_tree_scope=scope,
            ranked_causes=[{**item, "title": item["name"]} for item in candidates],
            hints=hints,
        )
    ]
    context = {
        "experiment_id": metadata.experiment.code,
        "experiment_version": metadata.package.version,
        "experiment_version_id": offline_id,
        "experiment_package_hash": bundle.manifest.package_hash,
        "experiment_template": {"template_id": metadata.experiment.code},
        "device_id": "offline-fixture-device",
    }
    record = SimpleNamespace(
        id=f"offline-diagnosis:{scenario.id}",
        experiment_id=metadata.experiment.code,
        experiment_version=metadata.package.version,
        experiment_version_id=offline_id,
        context_snapshot=context,
        is_test_data=True,
        matched_rules=[
            {
                "rule_id": "offline-rule",
                "error_type": scenario.error_type,
                "summary": "合成场景，仅用于调用预检",
                "evidence": [
                    {"fact": row.fact, "observed_value": "synthetic"} for row in scenario.evidence
                ],
            }
        ],
    )
    state = {
        "error_type": scenario.error_type,
        "device_status": "unknown",
        "experiment_context": {
            "experiment_id": metadata.experiment.code,
            "version": metadata.package.version,
        },
        "fault_tree_candidates": candidates,
        "evidence_registry": [item.model_dump() for item in scenario.evidence],
        "allowed_verification_actions": actions,
        # No model output is fabricated for the second-stage rehearsal.
        "reasoning_status": "unknown",
        "reasoned_causes": [],
    }
    sources = [
        {
            "kind": "package",
            "id": offline_id,
            "version": metadata.package.version,
            "hash": bundle.manifest.package_hash,
        }
    ]
    return record, guidance, state, sources


def _stage_report(stage, manifest, payload, candidate_ids, prompt_version, trace=()):
    selected = manifest["selected_ids"].get("case_ids", [])
    units = []
    for case_id in selected:
        if stage == "explanation":
            content = next(
                ref["content"]
                for ref in payload["knowledge"]
                if (ref.get("case_id") or ref["chunk_id"]) == case_id
            )
            applicability = json.loads(content).get("applicability", {})
        else:
            unit = {
                field: [
                    item
                    for item in payload["knowledge_constraints"].get(field, [])
                    if item.get("case_id") == case_id
                ]
                for field in CONSTRAINT_CASE_FIELDS
            }
            content = json.dumps(unit, ensure_ascii=False, separators=(",", ":"))
            mapping = unit.get("standard_fault_mappings", [])
            applicability = mapping[0].get("applicability", {}) if mapping else {}
        limits = applicability.get("limits_text")
        units.append(
            {
                "case_id": case_id,
                "cleaned_chars": len(content),
                "projection_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "applicability": {
                    "condition_status": applicability.get("condition_status"),
                    "limits_chars": len(limits) if isinstance(limits, str) else None,
                    "limits_sha256": hashlib.sha256(limits.encode()).hexdigest()
                    if isinstance(limits, str)
                    else None,
                },
            }
        )
    complete = manifest["required_complete"]
    status = "prepared" if complete and selected else "deterministic_fallback_expected"
    return {
        "stage": stage,
        "status": status,
        "prompt_version": prompt_version,
        "candidate_ids": candidate_ids,
        "selected_ids": selected,
        "omitted_ids": [case_id for case_id in candidate_ids if case_id not in selected],
        "units": units,
        "selection_trace": list(trace),
        "context_manifest": manifest,
        "required_dependencies": [
            "fixed_package_identity",
            "evidence_registry",
            "candidate_evidence_links",
            "allowed_actions",
        ],
        "provider_attempted": False,
    }


def preview_scenario(bundle, scenario: PreviewScenario, *, budgets=None, trusted_sources=None):
    """One input-only preview. The object and supplied package stay unchanged."""
    settings = preview_settings({**(budgets or {}), **scenario.budgets})
    record, guidance, state, sources = _scenario_state(bundle, scenario)
    cases = bundle.cases.cases if scenario.source_mode == "package" else scenario.fixture_cases
    matched, trace = match_case_candidates(
        cases, record, guidance, limit=settings.ai_knowledge_limit
    )
    references = case_references(matched)
    if scenario.source_mode == "controlled_test":
        sources.extend(
            {
                "kind": "case",
                "id": case.id,
                "version": case.version,
                "hash": payload_digest(case.model_dump(mode="json")),
                "offline_fixture": True,
            }
            for case in scenario.fixture_cases
        )
    state["knowledge_constraints"] = build_reasoning_knowledge_constraints(
        state["experiment_context"], references
    )
    state["knowledge_context"] = [item.model_dump(mode="json") for item in references]
    sensitive_sources = tuple(source for item in references for source in item._sensitive_sources)
    candidate_ids = [item.case_id for item in matched]
    from app.experiment_packages.registry import registry_report

    report = {
        "id": scenario.id,
        "mode": "offline_fixture",
        "source_mode": scenario.source_mode,
        "package": {
            "experiment_code": bundle.metadata.experiment.code,
            "version": bundle.metadata.package.version,
            "package_hash": bundle.manifest.package_hash,
            "version_id": sources[0]["id"],
            "release_status": bundle.metadata.package.status,
        },
        "scenario_sha256": payload_digest(scenario.model_dump(mode="json")),
        "budgets": {key: getattr(settings, key) for key in BUDGET_FIELDS},
        "structure": {"status": "valid"},
        "source_traceability": registry_report(
            bundle, package_version_id=sources[0]["id"], trusted_sources=trusted_sources
        ),
        "scope_authorization": "not_evaluated",
        "matcher_trace": trace,
        "matched_ids": candidate_ids,
        "stages": {},
        "fixture_source_hashes": {
            case.id: payload_digest(case.model_dump(mode="json")) for case in scenario.fixture_cases
        },
        "concept_text_provided": False,
        "step_text_provided": False,
    }
    report["budget_sha256"] = payload_digest(report["budgets"])
    for stage in scenario.stages:
        try:
            if stage == "reasoning":
                details = {}
                system, user, prompt_hash, evidence = _reasoning_prompt(
                    state,
                    sensitive_sources=(record.context_snapshot, *sensitive_sources),
                    settings=settings,
                    context_details=details,
                )
                payload = json.loads(user)
                prepared = seal_context(
                    stage,
                    payload,
                    [{"case_id": key} for key in details["case_ids"]],
                    sources,
                    settings,
                    system,
                    user,
                    prompt_hash,
                    omissions=details["omissions"],
                    evidence_ids=[item["id"] for item in evidence],
                    sensitive_sources=(state, record.context_snapshot, *sensitive_sources),
                )
                manifest = asdict(prepared.manifest)
                prompt_version = REASONING_PROMPT_VERSION
                selection_trace = details.get("trace", [])
            else:
                ai_input = build_safe_ai_input(
                    record,
                    guidance,
                    references,
                    settings,
                    episode_id=None,
                    user_question=None,
                    workflow_state=state,
                )
                details = {}
                ai_input, _, _, _ = prepare_explanation(
                    ai_input, settings, sources, context_details=details
                )
                payload = ai_input.model_dump(mode="json")
                manifest = ai_input._context_manifest
                prompt_version = settings.ai_prompt_version
                selection_trace = details["trace"]
            report["stages"][stage] = _stage_report(
                stage, manifest, payload, candidate_ids, prompt_version, selection_trace
            )
        except ProviderInputError as exc:
            report["stages"][stage] = {
                "stage": stage,
                "status": "deterministic_fallback_expected",
                "candidate_ids": candidate_ids,
                "selected_ids": [],
                "omitted_ids": candidate_ids,
                "reason_codes": [exc.code],
                "context_manifest": {"required_complete": False, "reason_codes": [exc.code]},
                "provider_attempted": False,
                "units": [],
            }
    registry_units = report["source_traceability"]["units"]
    for stage_report in report["stages"].values():
        for unit in stage_report["units"]:
            unit["source_mode"] = scenario.source_mode
            unit["material_refs"] = [
                {
                    key: registered[key]
                    for key in (
                        "unit_id",
                        "unit_hash",
                        "package_version_id",
                        "package_hash",
                        "depends_on",
                    )
                }
                for registered in registry_units
                if scenario.source_mode == "package"
                and registered["target"].get("entity_kind") == "case"
                and registered["target"].get("entity_id") == unit["case_id"]
            ]
            unit["fixture_source_hash"] = report["fixture_source_hashes"].get(unit["case_id"])
    report["stage_coverage"] = {
        "status": "covered"
        if set(scenario.stages) == {"reasoning", "explanation"}
        else "incomplete",
        "requested": scenario.stages,
        "completed": list(report["stages"]),
        "semantic_review": "not_run",
        "real_provider": "not_run",
        "hardware": "not_run",
    }
    return report


def source_identity():
    """Fingerprints of the actual pure runtime entry points and their local contracts."""
    paths = [
        "app/experiment_packages/context_preview.py",
        "app/experiment_packages/loader.py",
        "app/experiment_packages/schemas.py",
        "app/experiment_packages/registry.py",
        "app/knowledge/matcher.py",
        "app/knowledge/applicability.py",
        "app/knowledge/projection.py",
        "app/knowledge/validation.py",
        "app/ai/context_builder.py",
        "app/ai/context_sanitizer.py",
        "app/ai/context_contract.py",
        "app/ai/governance.py",
        "app/ai/output_contract.py",
        "app/schemas/knowledge_case.py",
        "app/cli/preview_package_context.py",
        "app/ai/reasoning.py",
        "app/ai/prompts.py",
        "app/ai/schemas.py",
        "app/core/config.py",
    ]
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return {
        "git_commit": commit,
        "source_fingerprints": {
            f"backend/{path}": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in paths
        },
    }


def check_expectations(cases, expectations):
    """Exact independent oracle; called after previews, never sent into a builder."""
    expected = expectations["cases"]
    if expectations.get("schema_version") != "package-context-expectations-v1":
        raise ValueError("unknown expectation schema")
    if {case["id"] for case in cases} != set(expected):
        raise ValueError("incomplete expectation inventory")
    results = {}
    for case in cases:
        oracle = expected[case["id"]]
        checks = {"matched_ids": case["matched_ids"] == oracle["matched_ids"]}
        reasons = {item["case_id"]: item["reason"] for item in case["matcher_trace"]}
        checks["matcher_reasons"] = reasons == oracle["matcher_reasons"]
        for stage, stage_oracle in oracle["stages"].items():
            actual = case["stages"][stage]
            checks[f"{stage}.selected_ids"] = actual["selected_ids"] == stage_oracle["selected_ids"]
            checks[f"{stage}.required_complete"] = (
                actual["context_manifest"]["required_complete"] == stage_oracle["required_complete"]
            )
            checks[f"{stage}.omission_counts"] = (
                actual["context_manifest"].get("omission_counts", {})
                == stage_oracle["omission_counts"]
            )
            units = {unit["case_id"]: unit for unit in actual["units"]}
            for case_id, required in stage_oracle.get("required_applicability", {}).items():
                applicability = units.get(case_id, {}).get("applicability", {})
                checks[f"{stage}.limits:{case_id}"] = (
                    applicability.get("limits_sha256")
                    == hashlib.sha256(required["limits_text"].encode()).hexdigest()
                    and applicability.get("condition_status") == required["condition_status"]
                )
        if set(oracle["stages"]) != set(case["stages"]):
            checks["stage_inventory"] = False
        results[case["id"]] = {"passed": all(checks.values()), "checks": checks}
    return results


def run_package_context_preview(
    inputs=INPUTS,
    *,
    package=None,
    budgets=None,
    expectations=None,
    strict=False,
    trusted_sources=None,
):
    report = {
        "report_format": "package-context-preview-v1",
        "mode": "offline_fixture",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "blocked",
        "cases": [],
        "contract_version": CONTEXT_CONTRACT_VERSION,
        "policy_version": CONTEXT_POLICY_VERSION,
        "strict": strict,
        "scope_authorization": "not_evaluated",
        "real_provider": {"status": "not_run", "calls": 0, "tokens": None, "cost": None},
        "semantic_review": {"status": "not_run", "passed": None},
        "hardware": {"status": "not_run", "passed": None},
    }
    if not Path(inputs).is_file() or (
        strict and (expectations is None or not Path(expectations).is_file())
    ):
        report["reason"] = "required_material_missing"
        return report
    try:
        input_document = json.loads(Path(inputs).read_text())
        parsed = PreviewInputs.model_validate(input_document)
        preview_settings(budgets or {})
        report["inputs_sha256"] = payload_digest(input_document)
        report.update(source_identity())
        for scenario in parsed.cases:
            path = Path(package) if package else ROOT / scenario.package
            if not path.is_dir() or any(not (path / name).is_file() for name in PACKAGE_FILES):
                report["reason"] = "required_package_missing"
                return report
            bundle, validation = load_experiment_package(path)
            result = preview_scenario(
                bundle, scenario, budgets=budgets, trusted_sources=trusted_sources
            )
            result["structure"]["checks"] = [item.code for item in validation.checks if item.passed]
            report["cases"].append(result)
        report["status"] = "analyzed"
        if strict:
            expected = json.loads(Path(expectations).read_text())
            report["expectations_sha256"] = payload_digest(expected)
            report["assertions"] = check_expectations(report["cases"], expected)
            report["status"] = (
                "passed"
                if all(value["passed"] for value in report["assertions"].values())
                else "failed"
            )
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        report["status"] = "error"
        report["error_type"] = type(exc).__name__
        report["reason"] = "preview_execution_or_material_invalid"
    return report


def preview_exit_code(report):
    if report["status"] == "blocked":
        return 2
    return 0 if report["status"] in {"analyzed", "passed"} else 1


def write_preview_report(report, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    lines = [
        "# 资料包调用预检",
        "",
        f"结果：{report['status']}；模式：offline_fixture。",
        "报告生成成功只表示分析完成。严格模式另核对独立预期；权限、语义、真实模型与硬件未验收。",
        "",
        "| 场景 | 阶段 | 实际选中案例 | 预计状态 |",
        "| --- | --- | --- | --- |",
    ]
    for case in report["cases"]:
        for stage, result in case["stages"].items():
            lines.append(
                f"| {case['id']} | {stage} | {', '.join(result['selected_ids']) or '无'}"
                f" | {result['status']} |"
            )
    lines += ["", "源码、资料、预算指纹及结构/来源/阶段覆盖的分开结果见同名 JSON。"]
    output.with_suffix(".md").write_text("\n".join(lines) + "\n")
