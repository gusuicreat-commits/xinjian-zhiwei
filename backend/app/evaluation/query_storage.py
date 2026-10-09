"""One evaluation-only task/receipt table. No production migration or ORM model.

Transactions serialize receipts; checkpoints contain only task IDs. Persistent owner
claims coordinate this single-host synchronous experiment without holding DB locks
across a provider/tool/human wait. A live owner's claim is never stolen.
"""

from __future__ import annotations

import os
import socket
import time
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

from sqlalchemy import JSON, Column, MetaData, String, Table, insert, select, update

from app.evaluation.query_contract import TaskContract, digest

metadata = MetaData()
tasks = Table(
    "query_eval_tasks",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("document", JSON, nullable=False),
)


class QueryRejected(RuntimeError):
    pass


class QueryStore:
    def __init__(self, engine):
        self.engine = engine

    def setup(self):
        if self.engine.dialect.name == "postgresql":
            with self.engine.connect() as conn:
                schema = conn.exec_driver_sql("SELECT current_schema()").scalar_one()
                if not schema.startswith("query_eval_"):
                    raise ValueError("query storage requires a dedicated query_eval_ schema")
        elif self.engine.dialect.name != "sqlite":
            raise ValueError("unsupported evaluation storage")
        metadata.create_all(self.engine)

    @contextmanager
    def edit(self, task_id):
        with self.engine.connect() as conn:
            if self.engine.dialect.name == "sqlite":
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                conn.begin()
                conn.exec_driver_sql("SET LOCAL lock_timeout = '1000ms'")
            try:
                doc = conn.execute(
                    select(tasks.c.document).where(tasks.c.id == task_id).with_for_update()
                ).scalar_one_or_none()
                if doc is None:
                    raise QueryRejected("unavailable")
                doc = deepcopy(doc)
                yield doc
                conn.execute(update(tasks).where(tasks.c.id == task_id).values(document=doc))
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def read(self, task_id):
        with self.engine.connect() as conn:
            doc = conn.execute(select(tasks.c.document).where(tasks.c.id == task_id))
            value = doc.scalar_one_or_none()
            if value is None:
                raise QueryRejected("unavailable")
            return deepcopy(value)

    def create(self, contract: TaskContract, initial=(), *, expires_at=None):
        records = contract.merge([], list(initial))
        now = time.time()
        document = {
            "contract": contract.model_dump(),
            "records": records,
            "checked": [],
            "question": None,
            "receipts": {},
            "steps": [],
            "pending": None,
            "revision": contract.scope.input_revision,
            "external_revision": 1,
            "expected_external_revision": 1,
            "authorized": True,
            "sources_valid": True,
            "cancelled": False,
            "status": "running",
            "policy": "model",
            "counts": {"queries": 0, "questions": 0, "selection_attempts": 0},
            "active_seconds": 0.0,
            "owner": None,
            "segment_started": None,
            "expires_at": expires_at if expires_at is not None else now + 1800,
        }
        with self.engine.begin() as conn:
            conn.execute(insert(tasks).values(id=contract.scope.task_id, document=document))
        return document

    @staticmethod
    def guard(doc, actor_id):
        contract = TaskContract.model_validate(doc["contract"])
        if not doc["authorized"] or actor_id != contract.scope.actor_id:
            return "blocked_authorization"
        if not doc["sources_valid"]:
            return "stale"
        if doc["external_revision"] != doc["expected_external_revision"]:
            return "stale"
        if doc["cancelled"]:
            return "cancelled"
        if time.time() >= doc["expires_at"]:
            return "stale"
        unfinished = (
            max(0.0, time.time() - doc["segment_started"])
            if doc["owner"] and doc["segment_started"] is not None
            else 0.0
        )
        if doc["active_seconds"] + unfinished >= contract.profile.active_seconds:
            return "stopped_budget"
        return None

    def claim(self, task_id, actor_id):
        token = uuid4().hex
        with self.edit(task_id) as doc:
            reason = self.guard(doc, actor_id)
            if reason:
                doc["status"] = reason
                return None
            owner = doc["owner"]
            if owner:
                if owner["host"] != socket.gethostname():
                    raise QueryRejected("owner_unresolved")
                try:
                    os.kill(owner["pid"], 0)
                except ProcessLookupError:
                    # A dead process's monotonic clock cannot be reused. Conservatively
                    # charge its entire unfinished wall-clock segment, up to the cap.
                    elapsed = max(0, time.time() - doc["segment_started"])
                    doc["active_seconds"] += elapsed
                    doc["owner"] = None
                    doc["segment_started"] = None
                else:
                    raise QueryRejected("already_running")
            reason = self.guard(doc, actor_id)
            if reason:
                doc["status"] = reason
                doc["owner"] = None
                doc["segment_started"] = None
                return None
            doc["owner"] = {"host": socket.gethostname(), "pid": os.getpid(), "token": token}
            doc["segment_started"] = time.time()
        return token

    def release(self, task_id, token, seconds):
        with self.edit(task_id) as doc:
            if doc["owner"] and doc["owner"]["token"] == token:
                doc["active_seconds"] += max(0, seconds)
                doc["owner"] = None
                doc["segment_started"] = None

    def submit_answer(
        self, task_id, actor_id, *, request_id, question_id, question_version, revision, value,
        recheck=None,
    ):
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 80:
            raise QueryRejected("invalid_request_id")
        if value not in {"on", "off", "unclear"}:
            raise QueryRejected("invalid_answer")
        payload = {
            "question_id": question_id,
            "question_version": question_version,
            "revision": revision,
            "value": value,
        }
        fingerprint = digest(payload)
        with self.edit(task_id) as doc:
            if self.guard(doc, actor_id):
                raise QueryRejected("unavailable")
            if recheck is not None:
                try:
                    recheck(doc)
                except Exception as exc:
                    raise QueryRejected("unavailable") from exc
            prior = doc["receipts"].get(request_id)
            if prior:
                if prior["hash"] != fingerprint:
                    raise QueryRejected("answer_conflict")
                return deepcopy({k: v for k, v in prior.items() if k != "value"})
            q = doc["question"]
            if (
                doc["status"] != "awaiting_answer"
                or not q
                or q["status"] != "pending"
                or q["id"] != question_id
                or q["version"] != question_version
                or type(revision) is not int
                or revision != q["revision"]
                or revision != doc["revision"]
            ):
                raise QueryRejected("answer_stale")
            receipt = {
                "request_id": request_id,
                "hash": fingerprint,
                "successor_revision": revision + 1,
                "value": value,
                "consumed": False,
                "source_kind": "student_report",
            }
            doc["receipts"][request_id] = receipt
            doc["revision"] += 1
            q["status"] = "answered"
            q["answer_request_id"] = request_id
            doc["status"] = "answer_ready"
            return deepcopy({k: v for k, v in receipt.items() if k != "value"})
