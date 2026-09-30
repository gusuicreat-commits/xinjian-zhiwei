"""Explicit runtime device identity for synthetic service fixtures only."""
from app.services.data_scope import find_active_experiment_session, is_demo_device, is_demo_session
from app.services.student_authorization import StudentActorContext


def demo_student_actor(db, device):
    session = find_active_experiment_session(db, device)
    assert session is not None and is_demo_device(device) and is_demo_session(db, session)
    return StudentActorContext(device.id, session.id, demo_device_hash=device.token_hash)
