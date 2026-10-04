"""Pure packing of already authorized snapshots; no retrieval, I/O or model calls."""

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from typing import Any

from app.ai.context_contract import ContextManifestV1, PreparedContext
from app.ai.context_sanitizer import (
    ProviderInputError,
    _safe_value,
    _sensitive_values,
    sanitize_text,
)
from app.ai.governance import estimate_prompt_tokens
from app.ai.schemas import AIDiagnosisInput, AIKnowledgeReference
from app.core.config import Settings


def payload_digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def select_knowledge(knowledge, settings: Settings, sensitive_values, *, trace=None):
    """Keep complete existing case projections. Collect secrets before dropping any unit."""
    secrets = set(sensitive_values)
    for ref in knowledge:
        for source in ref._sensitive_sources:
            secrets.update(_sensitive_values(source))
        secrets.update(_sensitive_values(ref.model_dump(mode="json")))
        try:
            secrets.update(_sensitive_values(json.loads(ref.content)))
        except (TypeError, ValueError):
            pass
    selected, seen, omissions = [], set(), {}
    for ref in knowledge:
        entry = {"case_id": ref.case_id or ref.chunk_id, "reason": "selected",
                 "cleaned_chars": None}
        if trace is not None:
            trace.append(entry)
        # Source identities are provenance, not prose that may be rewritten.
        for value in (ref.chunk_id, ref.case_id, ref.source_key, ref.source_version):
            if (
                value is not None
                and sanitize_text(value, sensitive_values=secrets, max_chars=None) != value
            ):
                raise ProviderInputError()
        key = (ref.source_type, ref.chunk_id, ref.source_version, payload_digest(ref.content))
        if key in seen:
            entry["reason"] = "duplicate"
            omissions["duplicate"] = omissions.get("duplicate", 0) + 1
            continue
        seen.add(key)
        try:
            structured = json.loads(ref.content)
        except (TypeError, ValueError):
            structured = ref.content
        try:
            cleaned = _safe_value(
                structured,
                sensitive_values=secrets,
                max_chars=None,
                strict=True,
                trusted_references={
                    ("caseId",): {ref.case_id or ref.chunk_id},
                    ("case_id",): {ref.case_id or ref.chunk_id},
                },
            )
            content = (
                cleaned
                if isinstance(structured, str)
                else json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
            )
            entry["cleaned_chars"] = len(content)
            if len(content) > settings.ai_knowledge_content_max_chars:
                raise ProviderInputError("AI_CONTEXT_INCOMPLETE")
            safe = ref.model_copy(
                update={
                    "source_uri": None,
                    "source_title": sanitize_text(
                        ref.source_title, sensitive_values=secrets, max_chars=200
                    ),
                    "locator": _safe_value(
                        ref.locator, sensitive_values=secrets, max_chars=200, strict=True
                    ),
                    "content": content,
                }
            )
        except ProviderInputError as exc:
            if exc.code != "AI_CONTEXT_INCOMPLETE":
                raise
            omissions["budget_omitted"] = omissions.get("budget_omitted", 0) + 1
            entry["reason"] = "budget_omitted"
            continue
        if len(selected) >= settings.ai_knowledge_limit:
            entry["reason"] = "policy_omitted"
            omissions["policy_omitted"] = omissions.get("policy_omitted", 0) + 1
            continue
        selected.append(safe)
    return selected, omissions


def selected_sources(sources, case_ids):
    """Filter the pre-I/O snapshot, never rebind it to a later source version."""
    result, seen = [], set()
    for source in sources:
        if source.get("kind") != "package" and source.get("id") not in case_ids:
            continue
        key = payload_digest(source)
        if key not in seen:
            result.append(deepcopy(source))
            seen.add(key)
    return result


CONSTRAINT_CASE_FIELDS = (
    # Every matched case has a mapping, in matcher order. Optional normal-state
    # projections must not promote lower-ranked cases when a budget is applied.
    "standard_fault_mappings",
    "normal_conditions",
    "teacher_confirmed_cases",
)


def select_reasoning_constraints(constraints, settings, sensitive_sources, *, trace=None):
    """All existing projections of a case are one optional unit, including conditions."""
    secrets = _sensitive_values(constraints)
    for source in sensitive_sources:
        secrets.update(_sensitive_values(source))
    ids = list(
        dict.fromkeys(
            item["case_id"]
            for field in CONSTRAINT_CASE_FIELDS
            for item in constraints.get(field, [])
            if item.get("case_id")
        )
    )
    selected, omissions = [], {}
    for case_id in ids:
        entry = {"case_id": case_id, "reason": "selected", "cleaned_chars": None}
        if trace is not None:
            trace.append(entry)
        if sanitize_text(case_id, sensitive_values=secrets, max_chars=None) != case_id:
            raise ProviderInputError()
        unit = {
            field: [item for item in constraints.get(field, []) if item.get("case_id") == case_id]
            for field in CONSTRAINT_CASE_FIELDS
        }
        try:
            safe = _safe_value(unit, sensitive_values=secrets, max_chars=None, strict=True)
            entry["cleaned_chars"] = len(
                json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
            )
            if entry["cleaned_chars"] > (
                settings.ai_knowledge_content_max_chars
            ):
                raise ProviderInputError("AI_CONTEXT_INCOMPLETE")
        except ProviderInputError as exc:
            if exc.code != "AI_CONTEXT_INCOMPLETE":
                raise
            omissions["budget_omitted"] = omissions.get("budget_omitted", 0) + 1
            entry["reason"] = "budget_omitted"
            continue
        if len(selected) >= settings.ai_knowledge_limit:
            entry["reason"] = "policy_omitted"
            omissions["policy_omitted"] = omissions.get("policy_omitted", 0) + 1
        else:
            selected.append(case_id)
    return filter_constraints(constraints, selected), selected, omissions


def filter_constraints(constraints, case_ids):
    return {
        key: [item for item in value if item.get("case_id") in case_ids]
        if key in CONSTRAINT_CASE_FIELDS
        else deepcopy(value)
        for key, value in constraints.items()
    }


def seal_context(
    stage,
    payload,
    references,
    sources,
    settings,
    system,
    user,
    prompt_hash,
    *,
    omissions=None,
    evidence_ids=(),
    sensitive_sources=(),
):
    secrets = set()
    for source in sensitive_sources:
        secrets.update(_sensitive_values(source))
    for source in sources:
        for key in ("id", "version", "package_id"):
            value = source.get(key)
            if value is not None and sanitize_text(
                value, sensitive_values=secrets, max_chars=None
            ) != value:
                raise ProviderInputError()
    case_ids = [
        ref.case_id or ref.chunk_id if isinstance(ref, AIKnowledgeReference) else ref["case_id"]
        for ref in references
    ]
    manifest = ContextManifestV1(
        stage=stage,
        prepared_source_refs=selected_sources(sources, set(case_ids)),
        selected_ids={
            "case_ids": list(dict.fromkeys(case_ids)),
            "evidence_ids": list(dict.fromkeys(evidence_ids)),
        },
        omission_counts=dict(omissions or {}),
        payload_sha256=payload_digest(payload),
        prompt_hash=prompt_hash,
        budget={
            "payload_chars": len(json.dumps(payload, ensure_ascii=False)),
            "case_count": len(set(case_ids)),
            "evidence_count": len(set(evidence_ids)),
            "estimated_input_tokens": estimate_prompt_tokens(system, user),
            "input_token_limit": settings.ai_input_token_limit,
            "knowledge_limit": settings.ai_knowledge_limit,
            "knowledge_content_max_chars": settings.ai_knowledge_content_max_chars,
        },
    )
    manifest.reason_codes = list(manifest.omission_counts)
    if not references and not manifest.omission_counts:
        manifest.reason_codes.append("no_eligible_reference")
    manifest.required_complete = manifest.budget["estimated_input_tokens"] <= (
        settings.ai_input_token_limit
    )
    if not manifest.required_complete:
        manifest.reason_codes.append("context_incomplete")
    return PreparedContext(payload, list(references), manifest)


def audit_manifest(manifest, *, attempts=0, cache_origin=None):
    result = asdict(manifest) if isinstance(manifest, ContextManifestV1) else deepcopy(manifest)
    result["provider_attempted"] = bool(attempts)
    result["submitted_source_refs"] = result.get("prepared_source_refs", []) if attempts else []
    result["cache_origin"] = cache_origin
    return result


def prepare_explanation(payload: AIDiagnosisInput, settings: Settings, sources=(), *,
                        context_details=None):
    from app.ai.prompts import build_prompts

    payload = payload.model_copy(deep=True)
    omissions = dict(payload._context_omissions)
    trace = deepcopy(payload._context_trace)
    while True:
        ids = {ref.case_id or ref.chunk_id for ref in payload.knowledge}
        if "knowledge_context" in payload.workflow_state:
            payload.workflow_state["knowledge_context"] = [
                ref
                for ref in payload.workflow_state["knowledge_context"]
                if (ref.get("case_id") or ref.get("chunk_id")) in ids
            ]
        system, user, prompt_hash = build_prompts(payload, settings.ai_prompt_version)
        if estimate_prompt_tokens(system, user) <= settings.ai_input_token_limit:
            break
        if not payload.knowledge:
            break
        dropped = payload.knowledge.pop()
        for entry in trace:
            if entry["case_id"] == (dropped.case_id or dropped.chunk_id):
                entry["reason"] = "budget_omitted"
        omissions["budget_omitted"] = omissions.get("budget_omitted", 0) + 1
    prepared = seal_context(
        "explanation",
        json.loads(user)["input"],
        payload.knowledge,
        sources,
        settings,
        system,
        user,
        prompt_hash,
        omissions=omissions,
        evidence_ids=[
            item["id"]
            for item in payload.workflow_state.get("evidence_registry", [])
            if item.get("id")
        ],
    )
    payload._context_manifest = asdict(prepared.manifest)
    if context_details is not None:
        context_details.update(trace=trace, omissions=omissions,
                               case_ids=[ref.case_id or ref.chunk_id for ref in payload.knowledge])
    return payload, system, user, prompt_hash
