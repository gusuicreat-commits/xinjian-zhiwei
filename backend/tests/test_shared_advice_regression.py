from copy import deepcopy

from test_case_applicability import case_record, diagnosis_record
from test_current_advice import advice_task as _advice_task
from test_current_advice import make_ai_result

from app.knowledge.matcher import match_case_candidates

advice_task = _advice_task


def test_conflicting_identity_cannot_select_text_only_case():
    diagnosis = diagnosis_record()
    diagnosis.context_snapshot['experiment_id'] = 'led'
    assert match_case_candidates([case_record()], diagnosis, [])[0] == []


def test_sensor_type_cannot_expand_experiment_scope():
    diagnosis = diagnosis_record()
    diagnosis.context_snapshot['readings'] = [{'sensor_type': 'led'}]
    assert match_case_candidates([case_record(experiment_type='led')], diagnosis, [])[0] == []


def test_unknown_identity_cannot_select_text_only_case():
    diagnosis = diagnosis_record(experiment_id=None, context_snapshot={})
    assert match_case_candidates([case_record()], diagnosis, [])[0] == []


def test_dashboard_does_not_deliver_invalid_historical_ai(advice_task, api_context):
    db, diagnosis, workflow = advice_task
    call = make_ai_result(db, diagnosis, workflow)
    call.output_json = {'summary': 'STALE-PRIVATE-ADVICE', 'steps': ['STALE-STEP']}
    db.commit()
    historical = deepcopy(call.output_json)
    response = api_context['client'].get(
        '/api/v1/student/dashboard', headers=api_context['headers'],
    )
    assert response.status_code == 200
    assert 'STALE-PRIVATE-ADVICE' not in str(response.json())
    db.refresh(call)
    assert call.output_json == historical


def test_invalid_contract_blocks_workflow_and_dashboard(advice_task, api_context):
    from app.services.diagnosis_workflow import serialize_workflow
    db, diagnosis, workflow = advice_task
    call = make_ai_result(db, diagnosis, workflow, current=True)
    call.output_json = {**call.output_json, 'steps': ['not allowed by contract']}
    db.commit()
    assert 'OLD MODEL' not in str(serialize_workflow(workflow).final_result)
    response = api_context['client'].get(
        '/api/v1/student/dashboard', headers=api_context['headers'],
    )
    assert response.status_code == 200
    assert 'OLD MODEL' not in str(response.json())


def test_detached_current_call_fails_closed(advice_task):
    from app.core.config import Settings
    from app.services.ai_diagnosis import serialize_ai_call
    db, diagnosis, workflow = advice_task
    call = make_ai_result(db, diagnosis, workflow, current=True)
    db.expunge(call)
    assert serialize_ai_call(call, Settings(_env_file=None)).explanation is None


def test_teacher_edit_preserved_and_later_call_cannot_replace_it(advice_task, api_context):
    from sqlalchemy import select
    from test_current_advice import add_call

    from app.models.base import utc_now
    from app.models.classroom import User
    from app.models.diagnosis_workflow import DiagnosisWorkflowReview

    db, diagnosis, workflow = advice_task
    make_ai_result(db, diagnosis, workflow, current=True)
    workflow.final_result = {**workflow.final_result, 'teacher_reviewed': True,
                             'summary': 'CURRENT TEACHER EDIT'}
    # Current teacher prose is backed by a persisted review, as in production;
    # a historical boolean alone must not authorize arbitrary model prose.
    db.add(DiagnosisWorkflowReview(
        workflow_run_id=workflow.id, reviewer_user_id=db.scalar(select(User.id)),
        action='edit', edited_result={'summary': 'CURRENT TEACHER EDIT'},
        created_at=utc_now(),
    ))
    later = add_call(db, diagnosis, workflow, 'explanation:feedback:later', current=True)
    later.output_json = {**later.output_json, 'summary': 'LATER UNBOUND OUTPUT'}
    diagnosis.ai_enhancement = {'call_record_id': later.id}
    db.commit()
    before = deepcopy(workflow.final_result)
    response = api_context['client'].get(
        '/api/v1/student/dashboard', headers=api_context['headers'],
    )
    assert response.status_code == 200
    assert response.json()['device_state_explanation']['status_summary'] == 'CURRENT TEACHER EDIT'
    assert 'LATER UNBOUND OUTPUT' not in str(response.json())
    db.refresh(workflow)
    assert workflow.final_result == before


def test_withdrawn_reference_blocks_bound_advice(advice_task):
    from app.services.current_advice import project_current_advice
    db, diagnosis, workflow = advice_task
    call = make_ai_result(db, diagnosis, workflow, current=True)
    call.knowledge_references = [{'chunk_id': 'withdrawn-case', 'source': 'case',
                                 'content': 'historical', 'score': 1}]
    db.commit()
    assert 'OLD MODEL' not in str(project_current_advice(db, workflow)[0])
