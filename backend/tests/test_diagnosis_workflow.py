from datetime import datetime, timezone
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.ai.clients import DisabledEmbeddingClient
from app.ai.diagnosis_graph import build_diagnosis_graph
from app.ai.tools import build_read_only_diagnosis_tools
from app.core.config import Settings
from app.core.security import hash_password
from app.diagnosis.workflow_schemas import (
    DiagnosisWorkflowReviewRequest,
    DiagnosisWorkflowStartRequest,
    TeacherEditedDiagnosis,
)
from app.models import (
    Classroom,
    Course,
    Device,
    DeviceBinding,
    DiagnosisFeedback,
    DiagnosisResult,
    DiagnosisWorkflowReview,
    DiagnosisWorkflowRun,
    TeachingAssignment,
    User,
)
from app.services.diagnosis_workflow import (
    WorkflowConflict,
    resume_workflow_with_feedback,
    review_workflow,
    start_workflow,
)


def _add_failure_log(api_context: dict[str, Any]) -> None:
    response = api_context["client"].post(
        "/api/v1/device/logs",
        headers=api_context["headers"],
        json={
            "level": "error",
            "message": "explicit LangGraph synthetic failure",
            "event_code": "SENSOR_READ_FAILED",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "is_test_data": True,
        },
    )
    assert response.status_code == 201


def _settings(**updates: Any) -> Settings:
    values = {
        "ai_enabled": False,
        "diagnosis_rag_trigger_score": 0.0,
        "diagnosis_teacher_review_score": 0.0,
        **updates,
    }
    return Settings(**values)


def _resume_feedback(db, graph, workflow, device, settings, action="resolved"):
    feedback = DiagnosisFeedback(
        device_id=device.id,
        diagnosis_result_id=workflow.diagnosis_result_id,
        action=action,
        note="合成反馈",
        is_test_data=True,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return resume_workflow_with_feedback(
        db, graph, workflow, feedback, device, settings
    )


class FailOnceAfterTerminalSaver(InMemorySaver):
    """Simulate the process boundary after a terminal business commit."""

    def __init__(self) -> None:
        super().__init__()
        self.terminal_failure_injected = False
        self.observed_statuses: list[str | None] = []

    def put(self, config, checkpoint, metadata, new_versions):
        raw_status = (checkpoint.get("channel_values") or {}).get("status")
        # Resume writes can carry LangGraph's Overwrite wrapper even though the
        # persisted channel value is the wrapped scalar.
        status_value = getattr(raw_status, "value", raw_status)
        status = str(status_value) if status_value is not None else None
        if status in {"completed", "rejected"} and not self.terminal_failure_injected:
            self.terminal_failure_injected = True
            self.observed_statuses.append(f"failed:{status}")
            raise RuntimeError("synthetic terminal checkpoint write failure")
        self.observed_statuses.append(status)
        return super().put(config, checkpoint, metadata, new_versions)

    def failure_was_injected(self) -> bool:
        return any(
            isinstance(item, str) and item.startswith("failed:") for item in self.observed_statuses
        )


def test_graph_wraps_existing_deterministic_pipeline_without_changing_facts(
    api_context: dict[str, Any],
) -> None:
    _add_failure_log(api_context)
    graph = build_diagnosis_graph(InMemorySaver())
    settings = _settings()
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device).where(Device.device_key == "phase2-test-device"))
        workflow = start_workflow(
            db,
            graph,
            device,
            settings,
            DiagnosisWorkflowStartRequest(lookback_seconds=60),
        )

        assert workflow.status == "waiting_feedback"
        workflow = _resume_feedback(db, graph, workflow, device, settings)
        assert workflow.status == "completed"
        assert workflow.graph_thread_id == f"diagnosis:{workflow.id}"
        assert workflow.node_trace == [
            "context_builder",
            "rule_engine",
            "fault_tree_analyzer",
            "ai_reasoning",
            "knowledge_service",
            "ai_explanation",
            "escalation_handler",
            "feedback_handler",
            "escalation_handler",
            "persist_result",
        ]
        assert [item["node"] for item in workflow.node_metrics] == [
            item for item in workflow.node_trace if item != "feedback_handler"
        ]
        assert all(item["duration_ms"] >= 0 for item in workflow.node_metrics)
        assert all(item["status"] == "succeeded" for item in workflow.node_metrics)
        assert workflow.resume_count == 1
        assert workflow.retrieval_audit["top_k"] == 0
        assert "full provider detail" not in str(workflow.node_metrics)
        assert workflow.final_result["rules_preserved"] is True
        assert workflow.final_result["knowledge_references"] == []
        assert "candidate_causes" in workflow.final_result
        assert workflow.final_result["rule_hits"][0]["error_type"] == "SENSOR_READ_FAILED"
        diagnosis = db.get(DiagnosisResult, workflow.diagnosis_result_id)
        assert [item["rule_id"] for item in diagnosis.matched_rules] == [
            item["rule_id"] for item in workflow.final_result["rule_hits"]
        ]
        assert [item["error_type"] for item in diagnosis.matched_rules] == [
            item["error_type"] for item in workflow.final_result["rule_hits"]
        ]
        assert all(
            "details" not in evidence
            for hit in workflow.final_result["rule_hits"]
            for evidence in hit["evidence"]
        )
        assert diagnosis.ai_enhancement["status"] == "disabled"

        checkpoint = graph.get_state(
            {"configurable": {"thread_id": workflow.graph_thread_id}}
        ).values
        serialized = str(checkpoint)
        assert "explicit LangGraph synthetic failure" not in serialized
        assert "phase2-test-token-not-for-production" not in serialized
        assert checkpoint["context_ref"]["telemetry_summary"]["log_count"] == 1
        assert "ai_response" not in checkpoint

        public_payload = workflow.review_request or workflow.final_result or {}
        assert not any("text" in item for item in public_payload.get("knowledge_references", []))


def test_unresolved_feedback_resumes_same_workflow_and_waits_again(
    api_context: dict[str, Any],
) -> None:
    _add_failure_log(api_context)
    graph = build_diagnosis_graph(InMemorySaver())
    settings = _settings(
        diagnosis_teacher_max_attempts=3,
        diagnosis_teacher_duration_seconds=3600,
    )
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device).where(Device.device_key == "phase2-test-device"))
        workflow = start_workflow(
            db,
            graph,
            device,
            settings,
            DiagnosisWorkflowStartRequest(lookback_seconds=60),
        )
        original_thread = workflow.graph_thread_id

        workflow = _resume_feedback(
            db, graph, workflow, device, settings, action="unresolved"
        )

        assert workflow.status == "waiting_feedback"
        assert workflow.graph_thread_id == original_thread
        assert workflow.resume_count == 1
        assert workflow.final_result is None
        assert workflow.node_trace.count("ai_reasoning") == 2
        assert workflow.node_trace.count("ai_explanation") == 2
        checkpoint = graph.get_state(
            {"configurable": {"thread_id": workflow.graph_thread_id}}
        ).values
        assert checkpoint["attempt_count"] == 1
        assert checkpoint["student_feedback"]["action"] == "unresolved"


def test_terminal_checkpoint_failure_is_reconciled_without_duplicate_result(
    api_context: dict[str, Any],
) -> None:
    _add_failure_log(api_context)
    saver = FailOnceAfterTerminalSaver()
    graph = build_diagnosis_graph(saver)
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device).where(Device.device_key == "phase2-test-device"))
        workflow = start_workflow(
            db,
            graph,
            device,
            _settings(),
            DiagnosisWorkflowStartRequest(lookback_seconds=60),
        )

        workflow = _resume_feedback(db, graph, workflow, device, _settings())

        assert saver.failure_was_injected()
        assert workflow.status == "completed"
        assert db.query(DiagnosisResult).count() == 1
        assert db.query(DiagnosisWorkflowRun).count() == 1
        checkpoint = graph.get_state({"configurable": {"thread_id": workflow.graph_thread_id}})
        assert checkpoint.values["status"] == "completed"


def test_review_terminal_checkpoint_failure_reconciles_one_audit(
    api_context: dict[str, Any],
) -> None:
    """A replay after the review commit must reuse its formal audit row."""

    saver = FailOnceAfterTerminalSaver()
    graph = build_diagnosis_graph(saver)
    settings = _settings(
        diagnosis_rag_trigger_score=1.0,
        diagnosis_teacher_review_score=1.0,
    )
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device).where(Device.device_key == "phase2-test-device"))
        workflow = start_workflow(
            db,
            graph,
            device,
            settings,
            DiagnosisWorkflowStartRequest(lookback_seconds=60),
        )
        teacher = User(
            username="graph-review-checkpoint-replay",
            display_name="合成审核重放教师",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        db.add(teacher)
        db.commit()

        workflow = review_workflow(
            db,
            graph,
            workflow,
            teacher,
            settings,
            DiagnosisWorkflowReviewRequest(
                action="approve",
                comment="checkpoint 失败后不得重复记录",
            ),
        )

        assert saver.failure_was_injected()
        assert workflow.status == "completed"
        assert workflow.resume_count == 1
        reviews = list(db.scalars(select(DiagnosisWorkflowReview)))
        assert len(reviews) == 1
        assert reviews[0].comment == "checkpoint 失败后不得重复记录"
        checkpoint = graph.get_state({"configurable": {"thread_id": workflow.graph_thread_id}})
        assert checkpoint.values["status"] == "completed"


def test_public_knowledge_reference_drops_nested_untrusted_metadata() -> None:
    from app.ai.diagnosis_graph import _knowledge_state_reference
    from app.ai.schemas import AIKnowledgeReference
    from app.services.diagnosis_workflow import _public_knowledge_reference

    checkpoint_ref = _knowledge_state_reference(
        AIKnowledgeReference(
            chunk_id="safe-chunk",
            source_key="safe-source",
            source_title="safe title",
            source_type="manual",
            source_uri=None,
            locator={
                "page": 7,
                "content": "nested private content",
                "private_note": "teacher secret",
            },
            content="Authorization: Bearer full-checkpoint-secret",
            similarity=0.01,
            is_test_data=True,
        )
    )
    checkpoint_serialized = str(checkpoint_ref)
    assert "full-checkpoint-secret" not in checkpoint_serialized
    assert "nested private content" not in checkpoint_serialized
    assert checkpoint_ref["metadata"]["locator"] == {"page": 7}

    projected = _public_knowledge_reference(
        {
            "chunk_id": "safe-chunk",
            "source_id": "safe-source",
            "title": "safe title",
            "score": 0.01,
            "text": "full private content",
            "metadata": {
                "source_type": "manual",
                "review_status": "approved",
                "private_note": "internal-only",
                "locator": {
                    "page": 7,
                    "section": "setup",
                    "content": "nested private content",
                    "private_note": "teacher secret",
                },
            },
        }
    )

    serialized = str(projected)
    assert projected["metadata"]["locator"] == {"page": 7, "section": "setup"}
    assert "private content" not in serialized
    assert "teacher secret" not in serialized
    assert "internal-only" not in serialized


def test_graph_has_one_structured_knowledge_control_plane(
    api_context: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The V2 graph matches structured knowledge once and never enters RAG."""

    from app.ai import diagnosis_graph

    calls = 0

    def fake_match(*_args: Any, **_kwargs: Any):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(
        diagnosis_graph,
        "_match_structured_knowledge",
        fake_match,
    )
    graph = build_diagnosis_graph(InMemorySaver())
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device).where(Device.device_key == "phase2-test-device"))
        workflow = start_workflow(
            db,
            graph,
            device,
            _settings(diagnosis_rag_trigger_score=0.0),
            DiagnosisWorkflowStartRequest(lookback_seconds=60),
        )
        assert workflow.status in {"waiting_feedback", "waiting_teacher"}
        assert workflow.needs_rag is False
        assert calls == 1
        assert "knowledge_service" in workflow.node_trace
        assert "retrieve_knowledge" not in workflow.node_trace


def test_structured_match_audit_keeps_explanatory_query(api_context: dict[str, Any]) -> None:
    graph = build_diagnosis_graph(InMemorySaver())
    question = "为什么采集不到温度？"
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device).where(Device.device_key == "phase2-test-device"))
        workflow = start_workflow(
            db,
            graph,
            device,
            _settings(
                diagnosis_rag_trigger_score=1.0,
                diagnosis_teacher_review_score=1.0,
            ),
            DiagnosisWorkflowStartRequest(lookback_seconds=60, question=question),
        )
        assert workflow.status == "waiting_teacher"
        assert workflow.retrieval_audit["mode"] == "structured_case_match"
        assert question in str(workflow.retrieval_audit["query"])


def test_failed_node_records_bounded_observability(
    api_context: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai import diagnosis_graph
    from app.ai.diagnosis_graph import DiagnosisNodeExecutionError

    def fail_context(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("full provider detail must not be persisted")

    monkeypatch.setattr(diagnosis_graph, "build_diagnosis_context", fail_context)
    graph = build_diagnosis_graph(InMemorySaver())
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device).where(Device.device_key == "phase2-test-device"))
        with pytest.raises(DiagnosisNodeExecutionError):
            start_workflow(
                db,
                graph,
                device,
                _settings(),
                DiagnosisWorkflowStartRequest(lookback_seconds=60),
            )

        workflow = db.scalar(select(DiagnosisWorkflowRun))
        assert workflow.status == "failed"
        assert workflow.current_node == "context_builder"
        assert workflow.node_metrics == [
            {
                "node": "context_builder",
                "duration_ms": workflow.node_metrics[0]["duration_ms"],
                "status": "failed",
            }
        ]
        assert workflow.error_messages == ["RuntimeError"]
        assert "full provider detail" not in str(workflow.error_messages)


def test_low_evidence_interrupt_can_be_edited_without_overwriting_rule_facts(
    api_context: dict[str, Any],
) -> None:
    graph = build_diagnosis_graph(InMemorySaver())
    settings = _settings(
        diagnosis_rag_trigger_score=1.0,
        diagnosis_teacher_review_score=1.0,
    )
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device).where(Device.device_key == "phase2-test-device"))
        workflow = start_workflow(
            db,
            graph,
            device,
            settings,
            DiagnosisWorkflowStartRequest(lookback_seconds=60, question="为什么没有数据？"),
        )
        assert workflow.status == "waiting_teacher"
        assert workflow.review_request["instruction"]
        assert all("text" not in item for item in workflow.review_request["retrieved_chunks"])

        teacher = User(
            username="graph-reviewer",
            display_name="合成图审核教师",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        db.add(teacher)
        db.commit()
        original_rules = list(workflow.review_request["rule_hits"])
        original_score = workflow.evidence_score
        original_level = workflow.guidance_level
        diagnosis = db.get(DiagnosisResult, workflow.diagnosis_result_id)
        workflow = review_workflow(
            db,
            graph,
            workflow,
            teacher,
            settings,
            DiagnosisWorkflowReviewRequest(
                action="edit",
                comment="补充更清晰的教师说明",
                edited_result=TeacherEditedDiagnosis(
                    summary="请先继续采集日志，再核对实验配置。",
                    possible_causes=["当前证据不足"],
                    steps=["保留现场并继续采集。"],
                    limitations=["教师未在现场确认硬件。"],
                ),
            ),
        )
        assert workflow.status == "completed"
        assert workflow.final_result["summary"] == "请先继续采集日志，再核对实验配置。"
        assert [item["rule_id"] for item in workflow.final_result["rule_hits"]] == [
            item["rule_id"] for item in diagnosis.matched_rules
        ]
        assert [item["error_type"] for item in workflow.final_result["rule_hits"]] == [
            item["error_type"] for item in diagnosis.matched_rules
        ]
        if original_rules:
            assert original_rules[0]["rule_id"] == diagnosis.matched_rules[0]["rule_id"]
        assert workflow.final_result["evidence_score"] == original_score
        assert workflow.final_result["guidance_level"] == original_level
        assert db.scalar(select(DiagnosisWorkflowReview)).action == "edit"


def test_reject_finishes_without_publishing_result(api_context: dict[str, Any]) -> None:
    graph = build_diagnosis_graph(InMemorySaver())
    settings = _settings(
        diagnosis_rag_trigger_score=1.0,
        diagnosis_teacher_review_score=1.0,
    )
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device).where(Device.device_key == "phase2-test-device"))
        workflow = start_workflow(
            db,
            graph,
            device,
            settings,
            DiagnosisWorkflowStartRequest(lookback_seconds=60),
        )
        teacher = User(
            username="graph-reject-reviewer",
            display_name="合成驳回教师",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        db.add(teacher)
        db.commit()
        workflow = review_workflow(
            db,
            graph,
            workflow,
            teacher,
            settings,
            DiagnosisWorkflowReviewRequest(action="reject", comment="需要更多现场证据"),
        )

        assert workflow.status == "rejected"
        assert workflow.final_result is None


def test_failed_resume_does_not_leave_review_and_can_be_retried(
    api_context: dict[str, Any],
) -> None:
    """The business audit is committed only after the checkpoint resumes."""

    checkpoint = InMemorySaver()
    graph = build_diagnosis_graph(checkpoint)
    settings = _settings(
        diagnosis_rag_trigger_score=1.0,
        diagnosis_teacher_review_score=1.0,
    )
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device).where(Device.device_key == "phase2-test-device"))
        workflow = start_workflow(
            db,
            graph,
            device,
            settings,
            DiagnosisWorkflowStartRequest(lookback_seconds=60),
        )
        teacher = User(
            username="graph-resume-retry-reviewer",
            display_name="合成恢复审核教师",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        db.add(teacher)
        db.commit()

        class FailingGraph:
            def invoke(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
                raise RuntimeError("synthetic checkpoint resume failure")

        try:
            review_workflow(
                db,
                FailingGraph(),
                workflow,
                teacher,
                settings,
                DiagnosisWorkflowReviewRequest(
                    action="approve",
                    comment="首次恢复失败，不应留下审核记录",
                ),
            )
        except RuntimeError as exc:
            assert str(exc) == "synthetic checkpoint resume failure"
        else:
            raise AssertionError("the synthetic resume failure must propagate")

        db.expire_all()
        workflow = db.get(DiagnosisWorkflowRun, workflow.id)
        assert workflow.status == "waiting_teacher"
        assert workflow.resume_count == 0
        assert db.scalar(select(DiagnosisWorkflowReview)) is None

        workflow = review_workflow(
            db,
            graph,
            workflow,
            teacher,
            settings,
            DiagnosisWorkflowReviewRequest(action="approve", comment="恢复后重试"),
        )
        assert workflow.status == "completed"
        assert workflow.resume_count == 1
        reviews = list(db.scalars(select(DiagnosisWorkflowReview)))
        assert len(reviews) == 1
        assert reviews[0].comment == "恢复后重试"


def test_duplicate_review_is_rejected_without_duplicate_audit(
    api_context: dict[str, Any],
) -> None:
    graph = build_diagnosis_graph(InMemorySaver())
    settings = _settings(
        diagnosis_rag_trigger_score=1.0,
        diagnosis_teacher_review_score=1.0,
    )
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device).where(Device.device_key == "phase2-test-device"))
        workflow = start_workflow(
            db,
            graph,
            device,
            settings,
            DiagnosisWorkflowStartRequest(lookback_seconds=60),
        )
        teacher = User(
            username="graph-idempotent-reviewer",
            display_name="合成幂等审核教师",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        db.add(teacher)
        db.commit()
        request = DiagnosisWorkflowReviewRequest(action="approve", comment="仅应保存一次")
        workflow = review_workflow(db, graph, workflow, teacher, settings, request)

        try:
            review_workflow(db, graph, workflow, teacher, settings, request)
        except WorkflowConflict as exc:
            assert "not waiting" in str(exc)
        else:
            raise AssertionError("a completed workflow must reject duplicate review")

        assert workflow.resume_count == 1
        assert len(list(db.scalars(select(DiagnosisWorkflowReview)))) == 1


def test_terminal_node_replay_keeps_one_formal_review(
    api_context: dict[str, Any],
) -> None:
    """A replay after a checkpoint write failure must not duplicate business facts."""

    graph = build_diagnosis_graph(InMemorySaver())
    settings = _settings(
        diagnosis_rag_trigger_score=1.0,
        diagnosis_teacher_review_score=1.0,
    )
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device).where(Device.device_key == "phase2-test-device"))
        workflow = start_workflow(
            db,
            graph,
            device,
            settings,
            DiagnosisWorkflowStartRequest(lookback_seconds=60),
        )
        teacher = User(
            username="graph-terminal-replay-reviewer",
            display_name="合成终结节点重放教师",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        db.add(teacher)
        db.commit()
        workflow = review_workflow(
            db,
            graph,
            workflow,
            teacher,
            settings,
            DiagnosisWorkflowReviewRequest(action="approve", comment="只保存一个正式审核"),
        )

        from app.ai.diagnosis_graph import DiagnosisGraphContext, persist_result

        checkpoint = graph.get_state(
            {"configurable": {"thread_id": workflow.graph_thread_id}}
        ).values
        persist_result(
            checkpoint,
            type(
                "SyntheticRuntime",
                (),
                {
                    "context": DiagnosisGraphContext(
                        db=db,
                        device=device,
                        settings=settings,
                        review_payload={
                            "action": "approve",
                            "comment": "只保存一个正式审核",
                            "edited_result": None,
                            "reviewer_user_id": teacher.id,
                        },
                    )
                },
            )(),
        )

        db.refresh(workflow)
        assert workflow.status == "completed"
        assert workflow.resume_count == 1
        assert len(list(db.scalars(select(DiagnosisWorkflowReview)))) == 1


def test_checkpoint_serialization_excludes_request_and_review_secrets(
    api_context: dict[str, Any],
) -> None:
    graph = build_diagnosis_graph(InMemorySaver())
    settings = _settings(
        diagnosis_rag_trigger_score=1.0,
        diagnosis_teacher_review_score=1.0,
    )
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device).where(Device.device_key == "phase2-test-device"))
        workflow = start_workflow(
            db,
            graph,
            device,
            settings,
            DiagnosisWorkflowStartRequest(
                lookback_seconds=60,
                question="请排查设备，Authorization: Bearer checkpoint-secret-token",
            ),
        )
        teacher = User(
            username="graph-secret-reviewer",
            display_name="合成敏感数据审核教师",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        db.add(teacher)
        db.commit()
        workflow = review_workflow(
            db,
            graph,
            workflow,
            teacher,
            settings,
            DiagnosisWorkflowReviewRequest(
                action="approve",
                comment="教师备注 api_key=teacher-review-secret",
            ),
        )

        serialized = str(
            graph.get_state({"configurable": {"thread_id": workflow.graph_thread_id}}).values
        )
        assert "checkpoint-secret-token" not in serialized
        assert "teacher-review-secret" not in serialized
        assert "phase2-test-token-not-for-production" not in serialized


def test_workflow_models_are_part_of_test_metadata(api_context: dict[str, Any]) -> None:
    with api_context["session_factory"]() as db:
        assert db.scalar(select(DiagnosisWorkflowRun)) is None
        assert db.scalar(select(DiagnosisWorkflowReview)) is None


def test_teacher_scope_fixture_can_link_workflow_device(api_context: dict[str, Any]) -> None:
    with api_context["session_factory"]() as db:
        teacher = User(
            username="scope-teacher",
            display_name="合成范围教师",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        course = Course(code="GRAPH", title="合成图课程", is_test_data=True)
        db.add_all([teacher, course])
        db.flush()
        classroom = Classroom(
            course_id=course.id,
            code="GRAPH-A",
            name="合成图班级",
            is_test_data=True,
        )
        db.add(classroom)
        db.flush()
        device = db.scalar(select(Device).where(Device.device_key == "phase2-test-device"))
        db.add_all(
            [
                TeachingAssignment(class_id=classroom.id, user_id=teacher.id),
                DeviceBinding(
                    device_id=device.id,
                    class_id=classroom.id,
                    student_user_id=None,
                    is_active=True,
                ),
            ]
        )
        db.commit()
        assert teacher.id


def test_langchain_tool_allowlist_is_read_only(api_context: dict[str, Any]) -> None:
    with api_context["session_factory"]() as db:
        tools = build_read_only_diagnosis_tools(
            db,
            _settings(),
            DisabledEmbeddingClient(),
            include_test_data=True,
        )
        names = {item.name for item in tools}
        assert names == {
            "get_fault_tree_path",
            "get_rule_explanation",
            "search_approved_fault_knowledge",
        }
        assert not any(
            blocked in name
            for name in names
            for blocked in ("sql", "shell", "http", "write", "device_control")
        )


def test_production_rejects_in_memory_checkpointing() -> None:
    try:
        Settings(app_env="production", diagnosis_checkpoint_backend="memory")
    except ValueError as exc:
        assert "postgres checkpoint backend" in str(exc)
    else:
        raise AssertionError("production must not accept volatile checkpoints")


def test_checkpoint_dsn_rejects_sqlalchemy_driver_prefix() -> None:
    with pytest.raises(ValueError, match="Psycopg postgresql"):
        Settings(
            diagnosis_checkpoint_backend="postgres",
            diagnosis_checkpoint_dsn=("postgresql+psycopg://user:password@postgres/database"),
        )
