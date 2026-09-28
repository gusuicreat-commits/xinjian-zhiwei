"""Explicit maintenance CLI; no retention policy or destructive history deletion."""

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import MemoryEvent
from app.services.memory_governance import process_stop_cache
from app.services.memory_restore import export_registry, replay_registry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation", choices=["clear-stopped-caches", "export-stops", "replay-stops"]
    )
    parser.add_argument("--file", type=Path)
    parser.add_argument("--isolated-restore", action="store_true")
    args = parser.parse_args()
    if args.operation != "clear-stopped-caches" and not args.file:
        parser.error("--file is required")
    if args.operation == "replay-stops" and not args.isolated_restore:
        parser.error("replay-stops requires an explicitly selected isolated restore database")
    with SessionLocal() as db:
        if args.operation == "export-stops":
            # Refuse accidental overwrite of the independently retained restore registry.
            with args.file.open("x", encoding="utf-8") as destination:
                json.dump(export_registry(db), destination, ensure_ascii=False, indent=2)
            print(
                "Stop registry exported; retain independently and verify freshness before restore."
            )
        elif args.operation == "replay-stops":
            print(
                json.dumps(
                    replay_registry(db, json.loads(args.file.read_text())), ensure_ascii=False
                )
            )
        else:
            ids = list(
                db.scalars(
                    select(MemoryEvent.id)
                    .where(MemoryEvent.cache_cleanup_status == "pending")
                    .order_by(MemoryEvent.id)
                    .limit(100)
                )
            )
            results = [process_stop_cache(db, db.get(MemoryEvent, event_id)) for event_id in ids]
            print(
                json.dumps(
                    {
                        "events": len(results),
                        "deleted_caches": sum(row["deleted"] for row in results),
                        "all_copies_deleted": False,
                    }
                )
            )


if __name__ == "__main__":
    main()
