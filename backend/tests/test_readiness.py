def test_readiness_reports_missing_external_inputs_without_faking_ready(
    api_context: dict[str, object],
) -> None:
    response = api_context["client"].get("/api/v1/readiness/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "1.0.0"
    assert payload["overall"] == "blocked"
    assert payload["software_ready"] is True
    assert payload["demo_ready"] is True
    assert payload["hardware_ready"] is False
    assert payload["knowledge_ready"] is False
    assert payload["organization_ready"] is False
    assert payload["production_ready"] is False
    by_key = {item["key"]: item for item in payload["items"]}
    assert by_key["device_protocol"]["status"] == "ready"
    assert by_key["virtual_lab"]["status"] == "test_only"
    assert by_key["real_hardware"]["status"] == "blocked"
    assert by_key["formal_knowledge"]["status"] == "blocked"
    assert by_key["ai"]["status"] == "not_required"
    assert by_key["production"]["status"] == "blocked"
