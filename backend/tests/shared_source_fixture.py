"""Persist explicitly constructed synthetic raw inputs used by unit fixtures."""

from app.models import DeviceHeartbeat, DeviceLog, SensorReading


def persist_context_fixture(db, device, context):
    for model, records in (
        (DeviceLog, context.logs),
        (DeviceHeartbeat, context.heartbeats),
        (SensorReading, context.readings),
    ):
        for item in records:
            if db.get(model, item.id):
                continue
            values = item.model_dump()
            values = {key: value for key, value in values.items() if key in model.__table__.columns}
            values.update(device_id=device.id)
            db.add(model(**values))
    db.flush()
    for item in [*context.observations, *context.events]:
        model = {
            "sensor_reading": SensorReading,
            "device_log": DeviceLog,
            "device_heartbeat": DeviceHeartbeat,
        }.get(item.source)
        if model is None or db.get(model, item.source_ref):
            continue
        if model is SensorReading:
            row = model(
                id=item.source_ref,
                device_id=device.id,
                sensor_type="synthetic",
                metric_key=getattr(item, "metric", "synthetic"),
                value=0,
                observed_at=getattr(item, "observed_at", context.evaluated_at),
                raw_payload=item.raw_payload,
                is_test_data=True,
            )
        elif model is DeviceLog:
            row = model(
                id=item.source_ref,
                device_id=device.id,
                level="INFO",
                message="synthetic",
                occurred_at=getattr(item, "occurred_at", context.evaluated_at),
                raw_payload=item.raw_payload,
                is_test_data=True,
            )
        else:
            row = model(
                id=item.source_ref,
                device_id=device.id,
                observed_at=context.evaluated_at,
                raw_payload=item.raw_payload,
                is_test_data=True,
            )
        db.add(row)
        db.flush()
