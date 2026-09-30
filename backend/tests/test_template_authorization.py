import pytest
from sqlalchemy import func, select

from app.models import ExperimentTemplate, ExperimentTemplateVersion, User
from app.services.auth import AuthorizationDenied
from app.services.experiment_templates import create_template


def test_template_create_requires_authenticated_actor(api_context):
    with api_context['session_factory']() as db:
        actor = db.scalar(select(User))
        before = db.scalar(select(func.count()).select_from(ExperimentTemplate))
        with pytest.raises(AuthorizationDenied):
            create_template(db, actor, code='NO-GRANT', title='synthetic', description=None,
                            version='1', content={}, is_test_data=True)
        db.rollback()
        assert db.scalar(select(func.count()).select_from(ExperimentTemplate)) == before


@pytest.mark.parametrize('operation', ['version', 'edit', 'transition'])
@pytest.mark.parametrize('revoke', ['session', 'role', 'inactive'])
def test_template_write_rechecks_current_grants(api_context, operation, revoke):
    from shared_write_authorization import authorize_write_fixture
    from sqlalchemy import delete

    from app.models.base import utc_now
    from app.models.classroom import AuthSession, user_roles
    from app.services.experiment_templates import (
        create_template_version,
        transition,
        update_content,
    )

    with api_context['session_factory']() as db:
        actor = authorize_write_fixture(db, db.scalar(select(User)), 'teacher')
        template, version = create_template(
            db, actor, code='CHECK-GRANT', title='synthetic', description=None,
            version='1', content={'objective': 'before'}, is_test_data=True,
        )
        if revoke == 'session':
            db.get(AuthSession, actor._actor_context.session_id).revoked_at = utc_now()
        elif revoke == 'role':
            db.execute(delete(user_roles).where(user_roles.c.user_id == actor.id))
        else:
            actor.is_active = False
        db.commit()
        with pytest.raises(AuthorizationDenied):
            if operation == 'version':
                create_template_version(db, actor, template, version='2', content={})
            elif operation == 'edit':
                update_content(db, actor, version, {'objective': 'unauthorized'})
            else:
                transition(db, actor, version, 'pending')
        db.rollback()
        db.refresh(version)
        assert version.status == 'draft'
        assert version.content_json == {'objective': 'before'}
        assert db.scalar(select(func.count()).select_from(ExperimentTemplateVersion).where(
            ExperimentTemplateVersion.template_id == template.id,
        )) == 1


def test_package_publication_requires_current_administrator(api_context):
    from shared_write_authorization import authorize_write_fixture
    from sqlalchemy import delete
    from test_experiment_packages import PACKAGE_ROOT

    from app.experiment_packages.loader import load_experiment_package, package_documents
    from app.models.classroom import user_roles
    from app.services.experiment_packages import (
        import_experiment_package,
        transition_experiment_package,
    )
    from app.services.rbac import assign_role, ensure_rbac_catalog

    with api_context['session_factory']() as db:
        actor = authorize_write_fixture(db, db.scalar(select(User)))
        bundle, _ = load_experiment_package(PACKAGE_ROOT / 'dht11_temperature_humidity')
        _, version = import_experiment_package(db, actor, package_documents(bundle))
        db.execute(delete(user_roles).where(user_roles.c.user_id == actor.id))
        assign_role(db, actor, ensure_rbac_catalog(db)['teacher'])
        db.commit()
        with pytest.raises(AuthorizationDenied):
            transition_experiment_package(db, actor, version, 'pending')
        db.rollback()
        db.refresh(version)
        assert version.status == 'draft'


@pytest.mark.parametrize('operation', ['version', 'edit', 'transition'])
def test_synthetic_actor_cannot_modify_formal_template(api_context, operation):
    from shared_write_authorization import authorize_write_fixture

    from app.services.experiment_templates import (
        create_template_version,
        transition,
        update_content,
    )

    with api_context['session_factory']() as db:
        actor = authorize_write_fixture(db, db.scalar(select(User)), 'teacher')
        actor.is_test_data = False
        db.commit()
        template, version = create_template(
            db, actor, code='FORMAL-SCOPE', title='synthetic test of formal scope',
            description=None, version='1', content={'objective': 'before'}, is_test_data=False,
        )
        actor.is_test_data = True
        db.commit()
        with pytest.raises(ValueError, match='separate test template'):
            if operation == 'version':
                create_template_version(db, actor, template, version='2', content={})
            elif operation == 'edit':
                update_content(db, actor, version, {'objective': 'after'})
            else:
                transition(db, actor, version, 'pending')
        db.rollback()
        db.refresh(version)
        db.refresh(template)
        assert not template.is_test_data
        assert version.status == 'draft'
        assert version.content_json == {'objective': 'before'}
        copied, _ = create_template(
            db, actor, code='TEST-COPY', title='test copy', description=None,
            version='1', content=version.content_json, is_test_data=True,
        )
        assert copied.is_test_data
