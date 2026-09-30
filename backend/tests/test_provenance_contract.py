from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.v1.routes.interventions import export_class_report, publish_message
from app.models import Classroom, Course, InterventionCase, User
from app.models.classroom import AuditEvent
from app.schemas.intervention import ClassroomMessageCreate
from app.services.rbac import assign_role, ensure_rbac_catalog


def actors(db, *, actor_test=False, class_test=False):
    user = User(username=uuid4().hex, display_name='Synthetic fixture', password_hash='unused',
                is_test_data=actor_test)
    course = Course(code=uuid4().hex, title='Synthetic fixture', is_test_data=False)
    db.add_all([user, course])
    db.flush()
    classroom = Classroom(course_id=course.id, code=uuid4().hex, name='Synthetic fixture',
                          is_test_data=class_test)
    db.add(classroom)
    roles = ensure_rbac_catalog(db)
    assign_role(db, user, roles['admin'])
    db.commit()
    from shared_authorization import session_actor_fixture

    session_actor_fixture(db, user)
    return user, classroom


@pytest.mark.parametrize('actor_test,class_test,explicit,expected', [
    (False, False, False, False), (True, False, False, True),
    (False, True, False, True), (False, False, True, True),
])
def test_message_keeps_any_test_source(api_context, actor_test, class_test, explicit, expected):
    with api_context['session_factory']() as db:
        actor, classroom = actors(db, actor_test=actor_test, class_test=class_test)
        result = publish_message(ClassroomMessageCreate(class_id=classroom.id,
            message='Synthetic message', audience='class', is_test_data=explicit), actor, db)
        assert result.is_test_data is expected


def test_mixed_export_cannot_be_marked_formal(api_context):
    with api_context['session_factory']() as db:
        actor, classroom = actors(db)
        db.add_all([InterventionCase(diagnosis_result_id=uuid4().hex, class_id=classroom.id,
                                    is_test_data=value) for value in (False, True)])
        db.commit()
        export_class_report(classroom.id, actor, db)
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == 'classroom.report_export'))
        assert event.is_test_data is True


@pytest.mark.parametrize('flags,explicit,expected', [
    ((False, False), False, False), ((False, True), False, True),
    ((False, None), False, True), ((), False, True), ((False,), True, True),
])
def test_provenance_unknown_or_test_never_becomes_formal(flags, explicit, expected):
    from app.services.provenance import derive_test_flag

    assert derive_test_flag(*flags, explicit=explicit) is expected
