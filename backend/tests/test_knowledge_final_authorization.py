import pytest
from sqlalchemy import delete
from test_knowledge_case_drafting import FakePolishClient

from app.core.config import Settings
from app.knowledge.case_drafting import apply_ai_assisted_polish, generate_ai_assisted_polish
from app.models.base import utc_now
from app.models.classroom import AuthSession, user_roles
from app.services.auth import AuthorizationDenied

pytest_plugins = ["test_knowledge_case_drafting"]


def polish_payload(draft):
    return {**draft.template_payload, "aiGeneratedFields": {"sourceIds": draft.source_ids}}


def test_direct_polish_cannot_omit_authenticated_identity(persisted_draft):
    db, draft = persisted_draft
    version = draft.version_no
    with pytest.raises(AuthorizationDenied) as caught:
        apply_ai_assisted_polish(db, draft, polish_payload(draft))
    assert caught.value.status_code == 401
    db.commit()  # a direct caller cannot accidentally commit the rejected revision claim
    db.refresh(draft)
    assert draft.version_no == version
    assert draft.polished_payload is None


def test_final_polish_rechecks_role_and_rolls_back_revision_claim(persisted_draft):
    db, draft = persisted_draft
    identity = db.info["case_actor"]
    version = draft.version_no
    db.execute(delete(user_roles).where(user_roles.c.user_id == identity.user_id))
    db.commit()
    with pytest.raises(AuthorizationDenied) as caught:
        apply_ai_assisted_polish(db, draft, polish_payload(draft), actor_context=identity)
    assert caught.value.status_code == 403
    db.commit()
    db.refresh(draft)
    assert draft.version_no == version
    assert draft.polished_payload is None


def test_session_revoked_during_provider_cannot_publish_wording(persisted_draft):
    db, draft = persisted_draft
    identity = db.info["case_actor"]
    version = draft.version_no

    class RevokingProvider(FakePolishClient):
        def complete_json(self, **kwargs):
            result = super().complete_json(**kwargs)
            db.get(AuthSession, identity.session_id).revoked_at = utc_now()
            db.commit()
            return result

    provider = RevokingProvider()
    with pytest.raises(AuthorizationDenied) as caught:
        generate_ai_assisted_polish(
            db, draft, Settings(ai_enabled=True), ai_client=provider, actor_context=identity
        )
    assert caught.value.status_code == 401
    assert len(provider.prompts) == 1
    db.commit()
    db.refresh(draft)
    assert draft.version_no == version
    assert draft.polished_payload is None
