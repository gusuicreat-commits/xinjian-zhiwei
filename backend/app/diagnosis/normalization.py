from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.diagnosis.schemas import (
    ContextEvent,
    ContextHeartbeat,
    ContextLog,
    ContextObservation,
    ContextReading,
    NormalizationResult,
    RawDeviceRecord,
    UnknownRawRecord,
)
from app.experiments.schemas import ExperimentDefinition

NormalizerAdapter = Callable[[list[RawDeviceRecord], ExperimentDefinition], NormalizationResult]


def _field(payload: dict[str, Any], path: str | None) -> Any:
    if path is None:
        return None
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _timestamp(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    return fallback


def mapping_adapter(
    records: list[RawDeviceRecord], definition: ExperimentDefinition
) -> NormalizationResult:
    observations: list[ContextObservation] = []
    events: list[ContextEvent] = []
    unknown: list[UnknownRawRecord] = []
    for index, record in enumerate(records):
        matching_mappings = [
            item
            for item in definition.normalization.mappings
            if all(_field(record.payload, key) == value for key, value in item.match.items())
        ]
        source_ref = record.id or f"raw:{index}"
        if len(matching_mappings) > 1:
            raise ValueError(
                f"raw record {source_ref} matched multiple normalization mappings: "
                f"{[item.id for item in matching_mappings]}"
            )
        mapping = matching_mappings[0] if matching_mappings else None
        if mapping is None:
            unknown.append(
                UnknownRawRecord(
                    source=record.source,
                    source_ref=source_ref,
                    reason="no normalization mapping matched",
                    received_at=record.received_at,
                    raw_payload=record.payload,
                )
            )
            events.append(
                ContextEvent(
                    id=f"unknown:{source_ref}",
                    type="unknown",
                    status="unknown",
                    occurred_at=record.received_at,
                    source=record.source,
                    source_ref=source_ref,
                    raw_payload=record.payload,
                )
            )
            continue
        occurred_at = _timestamp(
            _field(record.payload, mapping.timestamp_field), record.received_at
        )
        if mapping.output == "observation":
            metric = mapping.metric or _field(record.payload, mapping.metric_field)
            value = _field(record.payload, mapping.value_field)
            if metric is None or value is None:
                unknown.append(
                    UnknownRawRecord(
                        source=record.source,
                        source_ref=source_ref,
                        reason=f"normalization mapping {mapping.id} is missing required data",
                        received_at=record.received_at,
                        raw_payload=record.payload,
                    )
                )
                events.append(
                    ContextEvent(
                        id=f"unknown:{source_ref}:{mapping.id}",
                        type="unknown",
                        status="unknown",
                        occurred_at=occurred_at,
                        source=record.source,
                        source_ref=source_ref,
                        raw_payload=record.payload,
                    )
                )
                continue
            status = _field(record.payload, mapping.status_field) or mapping.default_status
            if status not in {"normal", "warning", "error", "unknown"}:
                status = "unknown"
            observations.append(
                ContextObservation(
                    id=f"observation:{source_ref}:{mapping.id}",
                    component_id=mapping.component_id,
                    interface_id=mapping.interface_id,
                    metric=str(metric),
                    value=value,
                    status=status,
                    observed_at=occurred_at,
                    source=record.source,
                    source_ref=source_ref,
                    raw_payload=record.payload,
                )
            )
        else:
            event_type = mapping.event_type or _field(record.payload, mapping.event_type_field)
            if event_type is None:
                unknown.append(
                    UnknownRawRecord(
                        source=record.source,
                        source_ref=source_ref,
                        reason=f"normalization mapping {mapping.id} is missing required data",
                        received_at=record.received_at,
                        raw_payload=record.payload,
                    )
                )
                events.append(
                    ContextEvent(
                        id=f"unknown:{source_ref}:{mapping.id}",
                        type="unknown",
                        status="unknown",
                        occurred_at=occurred_at,
                        source=record.source,
                        source_ref=source_ref,
                        raw_payload=record.payload,
                    )
                )
                continue
            events.append(
                ContextEvent(
                    id=f"event:{source_ref}:{mapping.id}",
                    type=str(event_type),
                    component_id=mapping.component_id,
                    interface_id=mapping.interface_id,
                    status=mapping.default_status,
                    occurred_at=occurred_at,
                    source=record.source,
                    source_ref=source_ref,
                    raw_payload=record.payload,
                )
            )
    return NormalizationResult(
        observations=observations,
        events=events,
        unknown_records=unknown,
    )


class NormalizerRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, NormalizerAdapter] = {}

    def register(self, name: str, adapter: NormalizerAdapter) -> None:
        if not name or name in self._adapters:
            raise ValueError(f"normalizer adapter is already registered or invalid: {name}")
        self._adapters[name] = adapter

    def normalize(
        self, records: list[RawDeviceRecord], definition: ExperimentDefinition
    ) -> NormalizationResult:
        adapter = self._adapters.get(definition.normalization.adapter)
        if adapter is None:
            raise ValueError(f"unknown normalizer adapter: {definition.normalization.adapter}")
        return adapter(records, definition)


normalizers = NormalizerRegistry()
normalizers.register("mapping", mapping_adapter)


def normalize_raw_device_data(
    records: list[RawDeviceRecord], definition: ExperimentDefinition
) -> NormalizationResult:
    """Normalize raw records without interpreting their diagnostic root cause."""

    return normalizers.normalize(records, definition)


def _component_for_sensor(sensor_type: str, definition: ExperimentDefinition | None) -> str:
    if definition is None:
        return sensor_type
    for component in definition.hardware.components:
        if sensor_type in {component.id, component.kind, component.model}:
            return component.id
    return sensor_type


def _interface_for_component(
    component_id: str | None, definition: ExperimentDefinition | None
) -> str | None:
    if component_id is None or definition is None:
        return None
    return next(
        (
            interface.id
            for interface in definition.interfaces
            if component_id in interface.component_ids
        ),
        None,
    )


def normalize_legacy_context(
    *,
    logs: list[ContextLog],
    heartbeats: list[ContextHeartbeat],
    readings: list[ContextReading],
    definition: ExperimentDefinition | None,
) -> NormalizationResult:
    """Compatibility adapter for the existing log/heartbeat/reading storage models."""

    observations = []
    events = []
    unknown = []
    for reading in readings:
        component_id = _component_for_sensor(reading.sensor_type, definition)
        observations.append(
            ContextObservation(
                id=f"reading:{reading.id}",
                component_id=component_id,
                interface_id=_interface_for_component(component_id, definition),
                metric=reading.metric_key,
                value=reading.value,
                unit=reading.unit,
                status="normal",
                observed_at=reading.observed_at,
                source="sensor_reading",
                source_ref=reading.id,
                raw_payload=reading.raw_payload,
            )
        )
    for heartbeat in heartbeats:
        events.append(
            ContextEvent(
                id=f"heartbeat:{heartbeat.id}",
                type="device_heartbeat",
                status="normal",
                occurred_at=heartbeat.observed_at,
                source="device_heartbeat",
                source_ref=heartbeat.id,
                raw_payload=heartbeat.raw_payload,
            )
        )
    for log in logs:
        component_id = log.raw_payload.get("component_id") or log.raw_payload.get("component")
        interface_id = log.raw_payload.get("interface_id") or log.raw_payload.get("interface")
        if log.event_code:
            events.append(
                ContextEvent(
                    id=f"log:{log.id}",
                    type=log.event_code,
                    component_id=str(component_id) if component_id else None,
                    interface_id=str(interface_id) if interface_id else None,
                    status="error" if log.level.lower() in {"error", "critical"} else "warning",
                    occurred_at=log.occurred_at,
                    source="device_log",
                    source_ref=log.id,
                    raw_payload=log.raw_payload,
                )
            )
        else:
            unknown.append(
                UnknownRawRecord(
                    source="device_log",
                    source_ref=log.id,
                    reason="log has no event_code",
                    received_at=log.occurred_at,
                    raw_payload=log.raw_payload or {"level": log.level, "message": log.message},
                )
            )
            events.append(
                ContextEvent(
                    id=f"unknown:log:{log.id}",
                    type="unknown",
                    status="unknown",
                    occurred_at=log.occurred_at,
                    source="device_log",
                    source_ref=log.id,
                    raw_payload=log.raw_payload or {"level": log.level, "message": log.message},
                )
            )
    return NormalizationResult(
        observations=observations,
        events=events,
        unknown_records=unknown,
    )
