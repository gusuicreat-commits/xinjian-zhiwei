from datetime import datetime, timedelta, timezone

import pytest

from app.models import DiagnosisResult
from app.services.diagnosis_episode import _new_evidence_after, confirmed_recovery


def pair():
    now = datetime.now(timezone.utc)
    previous = DiagnosisResult(
        device_id="test",
        evaluated_at=now - timedelta(seconds=10),
        ruleset_hash="same",
        is_test_data=True,
        context_snapshot={},
        matched_rules=[
            {"error_type": "SENSOR_READ_FAILED", "scope": {"kind": "component", "keys": ["sensor"]}}
        ],
    )
    current = DiagnosisResult(
        device_id="test",
        evaluated_at=now,
        ruleset_hash="same",
        is_test_data=True,
        matched_rules=[],
        context_snapshot={
            "normal_assessment": {"status": "normal", "checks": [{"status": "satisfied"}]},
            "observations": [
                {
                    "id": "mapped",
                    "source": "sensor_reading",
                    "source_ref": "new",
                    "component_id": "sensor",
                    "status": "normal",
                    "observed_at": (now - timedelta(seconds=1)).isoformat(),
                }
            ],
            "recheck_source_time_quality": {"sensor_reading:new": "device_reported"},
        },
    )
    return previous, current


@pytest.mark.parametrize(
    "boundary", ["heartbeat", "unrelated", "fallback", "missing_quality", "late"]
)
def test_legacy_recovery_cannot_bypass_recheck_evidence_rules(boundary):
    previous, current = pair()
    snapshot = current.context_snapshot
    observation = snapshot["observations"][0]
    if boundary == "heartbeat":
        snapshot["heartbeats"] = [{"observed_at": observation["observed_at"]}]
        snapshot["observations"] = []
    elif boundary == "unrelated":
        observation["component_id"] = "other"
    elif boundary == "fallback":
        snapshot["recheck_source_time_quality"]["sensor_reading:new"] = "server_fallback"
    elif boundary == "missing_quality":
        snapshot.pop("recheck_source_time_quality")
    elif boundary == "late":
        observation["observed_at"] = previous.evaluated_at.isoformat()
    assert not confirmed_recovery(current, previous)


def test_trusted_related_new_observation_can_confirm_recovery():
    previous, current = pair()
    assert confirmed_recovery(current, previous)


def test_unknown_time_quality_cannot_reopen_closed_fault():
    previous, current = pair()
    current.context_snapshot.pop("recheck_source_time_quality")
    assert not _new_evidence_after(current, {"reading_id:new"}, previous.evaluated_at)
