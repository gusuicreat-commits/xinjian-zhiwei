"""Shared, pure projection of eligible cases for runtime and offline preview."""

import json

from app.ai.schemas import AIKnowledgeReference


def case_references(cases) -> list[AIKnowledgeReference]:
    references = []
    for item in cases:
        ref = AIKnowledgeReference(
            chunk_id=item.case_id,
            source_key=item.source_ref,
            source_title=f"{item.experiment_type}: {item.symptom}",
            source_type="structured_case", source_uri=None, source_version=item.version,
            locator={"case_id": item.case_id},
            content=json.dumps({
                "caseId": item.case_id, "experimentType": item.experiment_type,
                "errorType": item.error_type, "symptom": item.symptom,
                "normalState": item.normal_state, "evidence": item.evidence,
                "possibleCauses": item.possible_causes, "solutionSteps": item.solution_steps,
                "teacherNotes": item.teacher_notes,
                "rootCause": {"value": item.root_cause_value, "status": item.root_cause_status},
                "applicability": item.applicability.model_dump(mode="json"),
            }, ensure_ascii=False, separators=(",", ":")),
            similarity=item.match_score,
            retrieval_scores={"structured_match": item.match_score},
            is_test_data=item.is_test_data,
        )
        ref._sensitive_sources = item._sensitive_sources
        references.append(ref)
    return references
