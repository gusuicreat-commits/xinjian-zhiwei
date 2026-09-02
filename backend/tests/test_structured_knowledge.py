from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.knowledge.loader import load_case_definitions
from app.knowledge.matcher import match_knowledge_cases
from app.models.diagnosis_result import DiagnosisResult
from app.models.knowledge import KnowledgeCase


def test_external_mvp_case_files_cover_five_experiments() -> None:
    cases = load_case_definitions()

    assert {item.experiment_type for item in cases} == {
        "dht11_temperature_humidity",
        "gpio_led_output",
        "gpio_button_input",
        "photosensor_adc",
        "ultrasonic_distance",
    }
    assert all(item.review_status == "pending" for item in cases)
    assert all(item.normal_state and item.solution_steps and item.teacher_notes for item in cases)


def test_matcher_uses_explicit_experiment_error_and_review_fields() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                KnowledgeCase(
                    id="approved-dht11",
                    experiment_type="dht11_temperature_humidity",
                    error_type="SENSOR_READ_FAILED",
                    symptom="DHT11 read failed",
                    normal_state={"metrics": ["temperature", "humidity"]},
                    evidence=[{"fact": "log_event_count"}],
                    possible_causes=["check wiring"],
                    solution_steps=["preserve logs"],
                    teacher_notes="reviewed fixture",
                    facts={"source_ids": ["test-evidence"]},
                    root_cause_value="check wiring",
                    root_cause_status="confirmed",
                    confirmed_by="teacher-test",
                    solution_record={"steps": ["preserve logs"]},
                    ai_generated_fields={},
                    source_type="real_experiment",
                    facts_locked=True,
                    quality_check_passed=True,
                    review_status="approved",
                    source_ref="test://approved-dht11",
                    version="1",
                    is_test_data=True,
                ),
                KnowledgeCase(
                    id="pending-dht11",
                    experiment_type="dht11_temperature_humidity",
                    error_type="SENSOR_READ_FAILED",
                    symptom="must not match",
                    normal_state={},
                    evidence=[],
                    possible_causes=[],
                    solution_steps=[],
                    teacher_notes=None,
                    review_status="pending",
                    source_ref="test://pending-dht11",
                    version="1",
                    is_test_data=True,
                ),
            ]
        )
        diagnosis = DiagnosisResult(
            device_id="test-device",
            evaluated_at=datetime.now(timezone.utc),
            ruleset_version="test",
            ruleset_hash="0" * 64,
            input_fingerprint="1" * 64,
            matched_rules=[
                {
                    "error_type": "SENSOR_READ_FAILED",
                    "summary": "read failed",
                    "evidence": [{"fact": "log_event_count", "observed_value": 1}],
                }
            ],
            evidence=[],
            context_snapshot={
                "experiment_template": {"template_id": "dht11_temperature_humidity"},
                "readings": [],
            },
            is_test_data=True,
        )
        db.add(diagnosis)
        db.commit()

        matched = match_knowledge_cases(db, diagnosis, [], limit=5)

        assert [item.case_id for item in matched] == ["approved-dht11"]
        assert matched[0].matched_on == ["error_type", "experiment_type", "evidence"]
        assert matched[0].match_score == 1.0
    engine.dispose()
