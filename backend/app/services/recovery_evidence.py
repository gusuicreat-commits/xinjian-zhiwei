"""Server-owned time provenance and scoped new evidence for every diagnosis entry."""

from datetime import datetime, timezone


def utc(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return (
        parsed.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None
        else parsed.astimezone(timezone.utc)
    )


def scoped_sources(snapshot, scope):
    if scope.get("kind") not in {"component", "interface"}:
        return {}
    field = "component_id" if scope["kind"] == "component" else "interface_id"
    return {
        f"{item.get('source')}:{item.get('source_ref')}": item
        for name in ("observations", "events")
        for item in snapshot.get(name, [])
        if item.get(field) in scope.get("keys", [])
        and item.get("type") != "device_heartbeat"
        and item.get("source") in {"device_log", "sensor_reading"}
        and item.get("source_ref")
    }


def fresh_related_evidence(snapshot, previous, scopes, cutoff, evaluated_at):
    """Unknown provenance/scope fails closed, including immutable historical snapshots."""
    if not scopes:
        return False
    quality = snapshot.get("recheck_source_time_quality") or {}
    for scope in scopes:
        old = scoped_sources(previous, scope)
        found = False
        for key, row in scoped_sources(snapshot, scope).items():
            if (
                key in old
                or row.get("status") not in {"normal", "warning", "error"}
                or quality.get(key) != "device_reported"
            ):
                continue
            try:
                observed = utc(row.get("observed_at") or row.get("occurred_at"))
            except (TypeError, ValueError):
                continue
            if utc(cutoff) < observed <= utc(evaluated_at):
                found = True
                break
        if not found:
            return False
    return True
