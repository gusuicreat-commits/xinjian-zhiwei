def test_readiness_reports_missing_external_inputs_without_faking_ready(
    api_context: dict[str, object],
) -> None:
    response = api_context["client"].get("/api/v1/readiness/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "1.0.0"
    assert payload["overall"] == "blocked"
    assert payload["software_ready"] is False
    assert payload["demo_ready"] is False
    assert payload["hardware_ready"] is False
    assert payload["knowledge_ready"] is False
    assert payload["organization_ready"] is False
    assert payload["production_ready"] is False
    by_key = {item["key"]: item for item in payload["items"]}
    assert by_key["device_protocol"]["status"] == "unverified"
    assert by_key["virtual_lab"]["status"] == "test_only"
    assert by_key["real_hardware"]["status"] == "unverified"
    assert by_key["formal_knowledge"]["status"] == "blocked"
    assert by_key["ai"]["status"] == "not_required"
    assert by_key["production"]["status"] == "blocked"


def test_approved_document_alone_does_not_make_formal_package_ready(api_context):
    from app.models.knowledge import KnowledgeDocument, KnowledgeSource

    with api_context["session_factory"]() as db:
        source = KnowledgeSource(
            source_key="readiness-fixture",
            source_type="fixture",
            title="Synthetic readiness fixture",
            is_test_data=False,
        )
        db.add(source)
        db.flush()
        db.add(
            KnowledgeDocument(
                source_id=source.id,
                title="Synthetic approved document",
                media_type="text/plain",
                content_hash="a" * 64,
                parser_name="fixture",
                parser_version="1",
                review_status="approved",
                is_test_data=False,
            )
        )
        db.commit()
    result = api_context["client"].get("/api/v1/readiness/status").json()
    assert not result["knowledge_ready"]
    assert (
        next(item for item in result["items"] if item["key"] == "approved_documents")["status"]
        == "ready"
    )


def test_loadable_published_non_test_package_does_not_require_real_cases(api_context):
    from test_experiment_packages import PACKAGE_ROOT

    from app.experiment_packages.loader import load_experiment_package, package_documents
    from app.models import User
    from app.services.experiment_packages import import_experiment_package

    with api_context["session_factory"]() as db:
        bundle, _ = load_experiment_package(PACKAGE_ROOT / "dht11_temperature_humidity")
        documents = package_documents(bundle)
        documents["knowledge/cases.yaml"]["cases"] = []
        # This fixture intentionally has no cases; remove their declared units,
        # rather than leaving dangling provenance selectors in the 1.1 package.
        registry = documents["metadata.yaml"]["content_registry"]
        registry["units"] = [unit for unit in registry["units"]
                             if unit["target"]["entity_kind"] != "case"]
        experiment, version = import_experiment_package(db, db.query(User).first(), documents)
        experiment.is_test_data = False
        version.is_test_data = False
        version.status = "published"
        db.commit()
        assert api_context["client"].get("/api/v1/readiness/status").json()["knowledge_ready"]
        version.package_hash = "b" * 64
        db.commit()
        assert not api_context["client"].get("/api/v1/readiness/status").json()["knowledge_ready"]
