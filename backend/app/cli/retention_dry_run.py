"""Report retention candidates without deleting any records."""

import argparse
import json
from datetime import timedelta

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import (
    AICallRecord,
    AuditEvent,
    DeviceHeartbeat,
    DeviceLog,
    SensorReading,
)
from app.models.base import utc_now


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, required=True)
    args = parser.parse_args()
    if args.days < 1:
        raise SystemExit("--days must be positive")
    cutoff = utc_now() - timedelta(days=args.days)
    models = {
        "device_logs": (DeviceLog, DeviceLog.received_at),
        "sensor_readings": (SensorReading, SensorReading.received_at),
        "device_heartbeats": (DeviceHeartbeat, DeviceHeartbeat.received_at),
        "ai_call_records": (AICallRecord, AICallRecord.created_at),
        "audit_events": (AuditEvent, AuditEvent.created_at),
    }
    with SessionLocal() as db:
        counts = {
            name: int(db.scalar(select(func.count(model.id)).where(column < cutoff)) or 0)
            for name, (model, column) in models.items()
        }
    print(
        json.dumps(
            {
                "mode": "dry-run",
                "cutoff": cutoff.isoformat(),
                "candidate_counts": counts,
                "deleted": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
