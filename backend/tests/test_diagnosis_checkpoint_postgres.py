"""Optional PostgreSQL checkpoint durability acceptance.

Run locally with, for example::

    TEST_DIAGNOSIS_CHECKPOINT_DSN=postgresql://... pytest \
        tests/test_diagnosis_checkpoint_postgres.py

The test is intentionally skipped in the default SQLite-only unit suite.  It uses
an isolated thread id and removes that thread after verification.
"""

from __future__ import annotations

import os
from typing import TypedDict
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class RestartState(TypedDict, total=False):
    marker: str
    review: dict[str, str]
    status: str


def _build_restart_graph(saver: PostgresSaver):
    def wait_for_review(state: RestartState) -> RestartState:
        decision = interrupt({"instruction": "approve"})
        return {"review": decision, "status": "completed"}

    builder = StateGraph(RestartState)
    builder.add_node("wait_for_review", wait_for_review)
    builder.add_edge(START, "wait_for_review")
    builder.add_edge("wait_for_review", END)
    return builder.compile(checkpointer=saver)


def test_postgres_checkpoint_survives_new_connection_and_simulated_restart() -> None:
    dsn = os.getenv("TEST_DIAGNOSIS_CHECKPOINT_DSN")
    if not dsn:
        pytest.skip("TEST_DIAGNOSIS_CHECKPOINT_DSN is not configured")

    thread_id = f"acceptance:checkpoint-restart:{uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}
    marker = f"restart-marker-{uuid4()}"
    with PostgresSaver.from_conn_string(dsn) as first_saver:
        first_saver.setup()
        first_graph = _build_restart_graph(first_saver)
        interrupted = first_graph.invoke({"marker": marker}, config=config)
        assert interrupted["__interrupt__"]

    # Closing the saver simulates the process/connection ending.  A freshly
    # compiled graph must restore and resume the pending interrupt by thread id.
    with PostgresSaver.from_conn_string(dsn) as second_saver:
        second_graph = _build_restart_graph(second_saver)
        before_resume = second_graph.get_state(config)
        assert before_resume.values["marker"] == marker
        assert before_resume.next == ("wait_for_review",)

        completed = second_graph.invoke(
            Command(resume={"action": "approve"}),
            config=config,
        )
        assert completed["status"] == "completed"
        assert completed["review"] == {"action": "approve"}
        assert second_graph.get_state(config).next == ()

        serialized = str(second_saver.get_tuple(config))
        assert "checkpoint-secret-token" not in serialized
        assert "teacher-review-secret" not in serialized
        second_saver.delete_thread(thread_id)
