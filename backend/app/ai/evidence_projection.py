"""Attribution of persisted evidence; never infer configuration or physical truth."""
from app.ai.context_sanitizer import _sensitive_values, sanitize_text


def evidence_reports(rows, *, sensitive_sources=()):
    rows = list(rows)
    secrets = set()
    for source in (*sensitive_sources, *(getattr(row, "raw_payload", {}) for row in rows)):
        secrets.update(_sensitive_values(source))
    result = []
    for item in rows:
        if sanitize_text(item.id, sensitive_values=secrets, max_chars=None) != item.id:
            continue
        value = item.normalized_value or {}
        kind = value.get("kind")
        if kind == "rule_fact":
            fact = f"规则证据:{value.get('fact')}={value.get('observed_value')}"
        elif kind == "observation":
            fact = (f"传感器:{value.get('metric')}={value.get('value')}"
                    f"{value.get('unit') or ''};status={value.get('status', 'unknown')}")
        elif kind == "event":
            fact = f"事件:{value.get('event_type')}={value.get('status') or 'observed'}"
        else:
            fact = f"证据:{item.evidence_type}"
        result.append({"id": item.id, "fact": sanitize_text(
            fact, sensitive_values=secrets, max_chars=None),
                       "source": item.source_type,
                       "status": str(value.get("status", "unknown"))
                       if kind == "observation" else "observed"})
    return result
