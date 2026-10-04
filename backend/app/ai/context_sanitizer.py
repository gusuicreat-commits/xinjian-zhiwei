from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from typing import Any

from app.ai.schemas import AIDiagnosisInput, AIKnowledgeReference
from app.core.config import Settings
from app.models.diagnosis_result import DiagnosisResult
from app.models.guidance_history import GuidanceHistory

PRIVACY_PROFILE = "provider-allowlist-v4"
SENSITIVE_KEY_PARTS = {
    "authorization",
    "apikey",
    "api_key",
    "password",
    "passwd",
    "secret",
    "token",
    "wifi",
    "studentname",
    "student_name",
    "studentid",
    "student_id",
    "class",
    "email",
    "phone",
    "identity",
    "teacherprivatenote",
    "teacher_private_note",
    "姓名",
    "学号",
    "班级",
    "手机号",
    "身份证",
    "邮箱",
    "密码",
    "密钥",
    "令牌",
    "教师私人备注",
}
TEXT_PATTERNS = (
    re.compile(r"authorization\s*[:=：]\s*bearer\s+\S+", re.IGNORECASE),
    re.compile(
        r"(?:api[_\s-]?key|password|passwd|device[_\s-]?token|wifi[_\s-]?password"
        r"|密码|密钥|设备令牌|Wi-?Fi密码)\s*[:=：]\s*\S+",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:学生姓名|student[_\s-]?name|学号|student[_\s-]?id|班级"
        r"|teacher[_\s-]?private[_\s-]?note|教师私人备注)\s*[:=：]\s*[^,，;；\n]+",
        re.IGNORECASE,
    ),
    re.compile(r"\b1[3-9]\d{9}\b"),
    re.compile(r"\b\d{17}[\dXx]\b"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
)
LOG_KEYS = ("level", "event_code", "occurred_at", "message")
CAUSE_KEYS = ("cause_id", "title", "score", "confidence")
HINT_KEYS = ("cause_id", "level", "text")
DEVICE_KEYS = {"deviceid", "devicekey", "anonymousdeviceid"}
ReferenceAllowlist = Mapping[tuple[str, ...], Collection[str]]


class ProviderInputError(ValueError):
    """Safe error classification: never expose the rejected value in an audit."""

    def __init__(self, code: str = "AI_INPUT_UNSAFE_REFERENCE"):
        self.code = code
        super().__init__(code)


def anonymous_device_id(device_id: str | None) -> str:
    normalized = (device_id or "unknown-device").strip().lower()
    digest = hashlib.sha256(f"xinjian-ai-device-v1:{normalized}".encode()).hexdigest()
    return f"anon-{digest[:16]}"


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9_\u4e00-\u9fff]", "", str(value).lower())


def _is_sensitive_key(key: Any) -> bool:
    normalized = _normalized_key(key).replace("_", "")
    return any(part.replace("_", "") in normalized for part in SENSITIVE_KEY_PARTS)


def _scalar_secrets(value: Any) -> set[str]:
    if isinstance(value, (str, int, float)):
        return {str(value)} if str(value) else set()
    items = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    return {secret for item in items for secret in _scalar_secrets(item)}


def _sensitive_values(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_sensitive_key(key) or _normalized_key(key).replace("_", "") in DEVICE_KEYS:
                found.update(_scalar_secrets(item))
            else:
                found.update(_sensitive_values(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_sensitive_values(item))
    return found


def sanitize_text(
    value: Any,
    *,
    sensitive_values: Iterable[str] = (),
    max_chars: int | None = 500,
) -> str:
    text = str(value or "")
    for secret in sorted(set(sensitive_values), key=len, reverse=True):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    for pattern in TEXT_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if max_chars is None else text[:max_chars]


def _safe_value(
    value: Any,
    *,
    sensitive_values: Iterable[str],
    max_chars: int | None = 500,
    field_name: str = "",
    path: tuple[str, ...] = (),
    trusted_references: ReferenceAllowlist | None = None,
    strict: bool = False,
) -> Any:
    if trusted_references is not None and path in trusted_references:
        if value is None:
            return None
        if (
            not isinstance(value, str)
            or value not in trusted_references[path]
            or sanitize_text(value, sensitive_values=sensitive_values,
                             max_chars=None) != value
        ):
            raise ProviderInputError()
        return value
    field_key = _normalized_key(field_name).replace("_", "")
    if field_key in DEVICE_KEYS and isinstance(value, str):
        return value if re.fullmatch(r"anon-[a-f0-9]{16}", value) else anonymous_device_id(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        cleaned = sanitize_text(value, sensitive_values=sensitive_values,
                                max_chars=None if strict else max_chars)
        if strict and max_chars is not None and len(cleaned) > max_chars:
            raise ProviderInputError("AI_CONTEXT_INCOMPLETE")
        return cleaned
    if isinstance(value, list):
        if strict and len(value) > 50:
            raise ProviderInputError("AI_CONTEXT_INCOMPLETE")
        return [
            _safe_value(
                item,
                sensitive_values=sensitive_values,
                max_chars=max_chars,
                path=(*path, "*"),
                trusted_references=trusted_references,
                strict=strict,
            )
            for item in (
                value if trusted_references and (*path, "*") in trusted_references else value[:50]
            )
        ]
    if isinstance(value, dict):
        # A dynamic key is also outbound text. Renaming it can change a metric
        # or collapse two evidence entries, so reject the enhancement instead.
        for key in value:
            if not _is_sensitive_key(key) and sanitize_text(
                key, sensitive_values=sensitive_values, max_chars=None
            ) != str(key):
                raise ProviderInputError("AI_INPUT_UNSAFE_KEY")
        return {
            str(key): _safe_value(
                item,
                sensitive_values=sensitive_values,
                max_chars=max_chars,
                field_name=str(key),
                path=(*path, str(key)),
                trusted_references=trusted_references,
                strict=strict,
            )
            for key, item in value.items()
            if not _is_sensitive_key(key)
        }
    return sanitize_text(
        value,
        sensitive_values=sensitive_values,
        max_chars=max_chars,
    )


def sanitize_provider_payload(
    payload: dict[str, Any],
    *,
    allowed_fields: Iterable[str],
    max_chars: int = 1000,
    trusted_references: ReferenceAllowlist | None = None,
    sensitive_sources: Iterable[Any] = (),
    strict: bool = False,
) -> dict[str, Any]:
    """Project business data for a Provider without mutating its source snapshot.

    Callers own the top-level field allowlist and append the trusted output
    schema afterwards. Sensitive values are collected before projection so
    secrets in omitted fields are also redacted from retained prose. Reference
    IDs remain exact only at verified paths ("*" denotes a list element) and
    within the caller's authoritative allowlist. Other IDs are ordinary data.
    Secrets are collected from the raw sources before projection, never sent.
    """
    allowed = set(allowed_fields)
    secrets = _sensitive_values(payload)
    for source in sensitive_sources:
        secrets.update(_sensitive_values(source))
    return _safe_value(
        {key: value for key, value in payload.items() if key in allowed},
        sensitive_values=secrets,
        max_chars=max_chars,
        trusted_references=trusted_references,
        strict=strict,
    )


def _evidence_log_ids(rule_matches: list[dict[str, Any]]) -> set[str]:
    return {
        str(detail["log_id"])
        for match in rule_matches
        for evidence in match.get("evidence", [])
        for detail in evidence.get("details", [])
        if detail.get("log_id")
    }


def _select_logs(
    context: dict[str, Any],
    rule_matches: list[dict[str, Any]],
    settings: Settings,
    sensitive_values: set[str],
) -> list[dict[str, Any]]:
    logs = list(context.get("logs") or [])
    evidence_ids = _evidence_log_ids(rule_matches)
    error_codes = {
        str(match.get("error_type")) for match in rule_matches if match.get("error_type")
    }
    selected = [
        item
        for item in logs
        if str(item.get("id")) in evidence_ids or str(item.get("event_code")) in error_codes
    ]
    if not selected:
        selected = [
            item
            for item in logs
            if str(item.get("level", "")).lower() in {"warning", "error", "critical"}
        ]
    if not selected:
        selected = logs[-3:]
    result = []
    for item in selected[-settings.ai_max_log_items :]:
        safe = {key: item.get(key) for key in LOG_KEYS if item.get(key) is not None}
        if "message" in safe:
            safe["message"] = sanitize_text(
                safe["message"],
                sensitive_values=sensitive_values,
                max_chars=500,
            )
        result.append(safe)
    return result


def _aggregate_readings(context: dict[str, Any]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str | None], list[dict[str, Any]]] = defaultdict(list)
    for item in context.get("readings") or []:
        key = (
            str(item.get("sensor_type") or "unknown"),
            str(item.get("metric_key") or "unknown"),
            item.get("unit"),
        )
        groups[key].append(item)
    result = []
    for (sensor_type, metric_key, unit), items in sorted(
        groups.items(), key=lambda item: (*item[0][:2], item[0][2] is not None, item[0][2] or "")
    ):
        numeric = [
            float(item["value"]) for item in items if isinstance(item.get("value"), (int, float))
        ]
        result.append(
            {
                "sensor_type": sensor_type,
                "metric_key": metric_key,
                "unit": unit,
                "sample_count": len(items),
                "minimum": min(numeric) if numeric else None,
                "maximum": max(numeric) if numeric else None,
                "latest": numeric[-1] if numeric else None,
                "first_observed_at": items[0].get("observed_at"),
                "last_observed_at": items[-1].get("observed_at"),
            }
        )
    return result


def _aggregate_heartbeats(context: dict[str, Any]) -> list[dict[str, Any]]:
    items = list(context.get("heartbeats") or [])
    if not items:
        return []
    return [
        {
            "count": len(items),
            "first_observed_at": items[0].get("observed_at"),
            "last_observed_at": items[-1].get("observed_at"),
        }
    ]


def _safe_rule_matches(
    rule_matches: list[dict[str, Any]],
    sensitive_values: set[str],
) -> list[dict[str, Any]]:
    return [
        {
            "rule_id": match.get("rule_id"),
            "error_type": match.get("error_type"),
            "summary": sanitize_text(
                match.get("summary"),
                sensitive_values=sensitive_values,
                max_chars=None,
            ),
            "evidence": [
                {
                    "fact": evidence.get("fact"),
                    "observed_value": _safe_value(
                        evidence.get("observed_value"),
                        sensitive_values=sensitive_values, max_chars=None, strict=True,
                    ),
                }
                for evidence in match.get("evidence", [])
            ],
        }
        for match in rule_matches
    ]


def _safe_guidance(
    guidance: list[GuidanceHistory], sensitive_values: set[str]
) -> list[dict[str, Any]]:
    return [
        {
            "tree_id": item.fault_tree_id,
            "tree_status": item.fault_tree_status,
            "hint_level": item.hint_level,
            "teacher_intervention_required": item.teacher_intervention_required,
            "ranked_causes": [
                {
                    key: (
                        sanitize_text(
                            cause.get(key),
                            sensitive_values=sensitive_values,
                            max_chars=None,
                        )
                        if key == "title"
                        else cause.get(key)
                    )
                    for key in CAUSE_KEYS
                    if cause.get(key) is not None
                }
                for cause in item.ranked_causes
            ],
            "hints": [
                {
                    key: (
                        sanitize_text(
                            hint.get(key),
                            sensitive_values=sensitive_values,
                            max_chars=None,
                        )
                        if key == "text"
                        else hint.get(key)
                    )
                    for key in HINT_KEYS
                    if hint.get(key) is not None
                }
                for hint in item.hints
            ],
        }
        for item in guidance
    ]


def _safe_knowledge(
    knowledge: list[AIKnowledgeReference],
    settings: Settings,
    sensitive_values: set[str],
) -> list[AIKnowledgeReference]:
    from app.ai.context_builder import select_knowledge

    return select_knowledge(knowledge, settings, sensitive_values)[0]


def build_safe_ai_input(
    record: DiagnosisResult,
    guidance: list[GuidanceHistory],
    knowledge: list[AIKnowledgeReference],
    settings: Settings,
    *,
    episode_id: str | None,
    user_question: str | None,
    workflow_state: dict[str, Any] | None = None,
) -> AIDiagnosisInput:
    context = dict(record.context_snapshot or {})
    sensitive_values = _sensitive_values(context) | _sensitive_values(workflow_state or {})
    for reference in knowledge:
        for source in reference._sensitive_sources:
            sensitive_values.update(_sensitive_values(source))
        try:
            sensitive_values.update(_sensitive_values(json.loads(reference.content)))
        except (TypeError, ValueError):
            pass
    experiment = context.get("experiment_template") or {}
    from app.ai.context_builder import select_knowledge

    trace = []
    safe_knowledge, omissions = select_knowledge(knowledge, settings, sensitive_values, trace=trace)
    payload = AIDiagnosisInput(
        diagnosis_result_id=record.id,
        episode_id=episode_id,
        anonymous_device_id=anonymous_device_id(context.get("device_id")),
        device_state={
            "evaluated_at": context.get("evaluated_at"),
            "last_seen_at": context.get("last_seen_at"),
            "experiment": {
                "template_id": sanitize_text(
                    experiment.get("template_id"),
                    sensitive_values=sensitive_values,
                    max_chars=None,
                ),
                "metric_ranges": _safe_value(
                    experiment.get("metric_ranges") or {},
                    sensitive_values=sensitive_values,
                    max_chars=None, strict=True,
                ),
            },
        },
        logs=_select_logs(context, record.matched_rules, settings, sensitive_values),
        sensor_readings=_aggregate_readings(context),
        heartbeats=_aggregate_heartbeats(context),
        rule_matches=_safe_rule_matches(record.matched_rules, sensitive_values),
        fault_tree_guidance=_safe_guidance(guidance, sensitive_values),
        knowledge=safe_knowledge,
        workflow_state={
            key: (workflow_state or {}).get(key)
            for key in (
                "device_status", "experiment_type", "logs", "sensor_data", "sensor_values",
                "experiment_context", "error_type", "evidence", "possible_causes",
                "reasoned_causes", "reasoning_status", "reasoning_summary", "missing_evidence",
                "next_verification_action", "evidence_conflict", "evidence_registry",
                "allowed_verification_actions", "knowledge_validation", "knowledge_context",
                "hint_level", "student_feedback", "historical_failures", "need_teacher_help",
                "diagnosis_status",
            )
            if key in (workflow_state or {})
        },
        allowed_evidence=[
            sanitize_text(
                f"{item.get('fact')}: {item.get('observed_value')}",
                sensitive_values=sensitive_values,
                max_chars=None,
            )
            for match in record.matched_rules
            for item in match.get("evidence", [])
        ],
        user_question=sanitize_text(
            user_question,
            sensitive_values=sensitive_values,
            max_chars=None,
        )
        if user_question
        else None,
        output_language=settings.ai_output_language,
        is_test_data=record.is_test_data,
    )
    state = workflow_state or {}
    references: dict[tuple[str, ...], Collection[str]] = {
        ("diagnosis_result_id",): {record.id},
        ("knowledge", "*", "chunk_id"): {item.chunk_id for item in knowledge},
        ("knowledge", "*", "case_id"): {
            item.case_id for item in knowledge if item.case_id is not None
        },
        ("knowledge", "*", "locator", "case_id"): {item.chunk_id for item in knowledge},
        ("rule_matches", "*", "rule_id"): {
            item["rule_id"] for item in record.matched_rules if item.get("rule_id")
        },
    }
    if episode_id is not None:
        references[("episode_id",)] = {episode_id}
    evidence_ids = {item["id"] for item in state.get("evidence_registry", []) if item.get("id")}
    cause_ids = {
        cause["cause_id"] for item in guidance for cause in item.ranked_causes
        if cause.get("cause_id")
    }
    # Workflow values came from the graph's independently validated reasoning.
    cause_ids.update(item["cause_id"] for item in state.get("reasoned_causes", [])
                     if item.get("cause_id"))
    for field in ("reasoned_causes", "possible_causes"):
        references[("workflow_state", field, "*", "cause_id")] = cause_ids
        references[("workflow_state", field, "*", "used_evidence_ids", "*")] = evidence_ids
    references[("workflow_state", "evidence_registry", "*", "id")] = evidence_ids
    actions = state.get("allowed_verification_actions", [])
    for field in ("action_id", "text"):
        references[("workflow_state", "allowed_verification_actions", "*", field)] = {
            item[field] for item in actions if item.get(field)
        }
    references[("fault_tree_guidance", "*", "hints", "*", "text")] = {
        hint["text"] for item in guidance for hint in item.hints if hint.get("text")
    }
    raw = payload.model_dump(mode="json")
    safe = sanitize_provider_payload(
        raw, allowed_fields=tuple(raw), trusted_references=references,
        sensitive_sources=(context, state, {"secret": list(sensitive_values)}),
        max_chars=max(2000, settings.ai_knowledge_content_max_chars), strict=True,
    )
    from app.ai.output_contract import project_explanation_state

    safe["workflow_state"] = project_explanation_state(safe["workflow_state"])
    result = AIDiagnosisInput.model_validate(safe)
    result._context_omissions = omissions
    result._context_trace = trace
    return result


def audit_snapshot(payload: AIDiagnosisInput) -> dict[str, Any]:
    full_input = payload.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(
            full_input,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "diagnosis_result_id": payload.diagnosis_result_id,
        "episode_id": payload.episode_id,
        "anonymous_device_id": payload.anonymous_device_id,
        "input_sha256": digest,
        "item_counts": {
            "logs": len(payload.logs),
            "sensor_reading_aggregates": len(payload.sensor_readings),
            "heartbeat_aggregates": len(payload.heartbeats),
            "rule_matches": len(payload.rule_matches),
            "fault_tree_guidance": len(payload.fault_tree_guidance),
            "knowledge": len(payload.knowledge),
        },
        "rule_ids": [item.get("rule_id") for item in payload.rule_matches if item.get("rule_id")],
        "error_types": [
            item.get("error_type") for item in payload.rule_matches if item.get("error_type")
        ],
        "knowledge_chunk_ids": [item.chunk_id for item in payload.knowledge],
        "privacy": {
            "profile": PRIVACY_PROFILE,
            "field_allowlist": True,
            "student_identity_removed": True,
            "device_id_anonymized": True,
            "logs_truncated": True,
            "sensor_readings_aggregated": True,
            "source_uri_removed": True,
        },
        "is_test_data": payload.is_test_data,
    }
