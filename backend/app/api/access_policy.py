"""Reviewed HTTP access inventory (XJ-008), independent of route discovery.

Keys use effective path templates, including root aliases and hidden routes.
``writes`` includes durable audit/cache/state changes, regardless of HTTP verb.
Transaction flags record a source review; this gate does not prove atomicity.
Permissions are capability expressions; roles are additional any-of constraints.
Service/handler checks are separate from dependency-level permission checks.
Conditional scope branches and demo exceptions are described in access_notes.
Missing device credentials have an explicit 422/detail.code protocol contract.
Only individually registered operations may use it; student query actors instead
reject missing identity with 401, even though they also support demo devices.
"""

from dataclasses import dataclass
from enum import Enum


class Auth(str, Enum):
    PUBLIC = "public"
    USER_TOKEN = "user_token"
    DEVICE_TOKEN = "device_token"
    STUDENT_ACTOR = "student_actor"  # Account or explicit synthetic demo device.
    REVIEW_TOKEN = "review_token"


@dataclass(frozen=True)
class AccessPolicy:
    auth: Auth
    permission: str | None
    writes: bool
    revalidates_in_transaction: bool | None = None  # Required bool for writes.
    public_reason: str | None = None
    roles: tuple[str, ...] = ()
    permission_checked_in_service: bool = False
    access_notes: str | None = None
    auth_resolved_in_handler: bool = False
    auth_handler: str | None = None  # Fully qualified endpoint callable.
    missing_credentials_status: int | None = None  # None requires 401 or 403.
    missing_credentials_code: str | None = None  # Exact detail.code for an exception.
    missing_credentials_source: str | None = None  # Callable producing the exception.
    transaction_evidence: str | None = None


ACCESS_POLICIES: dict[tuple[str, str], AccessPolicy] = {
    ("GET", "/openapi.json"): AccessPolicy(
        Auth.PUBLIC,
        None,
        False,
        public_reason="Public API schema/documentation and Swagger OAuth redirect; no user data.",
    ),
    ("HEAD", "/openapi.json"): AccessPolicy(
        Auth.PUBLIC,
        None,
        False,
        public_reason="Public API schema/documentation and Swagger OAuth redirect; no user data.",
    ),
    ("GET", "/docs"): AccessPolicy(
        Auth.PUBLIC,
        None,
        False,
        public_reason="Public API schema/documentation and Swagger OAuth redirect; no user data.",
    ),
    ("GET", "/redoc"): AccessPolicy(
        Auth.PUBLIC,
        None,
        False,
        public_reason="Public API schema/documentation and Swagger OAuth redirect; no user data.",
    ),
    ("GET", "/docs/oauth2-redirect"): AccessPolicy(
        Auth.PUBLIC,
        None,
        False,
        public_reason="Public API schema/documentation and Swagger OAuth redirect; no user data.",
    ),
    ("GET", "/health"): AccessPolicy(
        Auth.PUBLIC,
        None,
        False,
        public_reason="Public service health probe (root and versioned aliases).",
    ),
    ("GET", "/health/live"): AccessPolicy(
        Auth.PUBLIC,
        None,
        False,
        public_reason="Public service health probe (root and versioned aliases).",
    ),
    ("GET", "/health/ready"): AccessPolicy(
        Auth.PUBLIC,
        None,
        False,
        public_reason="Public service health probe (root and versioned aliases).",
    ),
    ("GET", "/health/dependencies"): AccessPolicy(
        Auth.PUBLIC,
        None,
        False,
        public_reason="Public service health probe (root and versioned aliases).",
    ),
    ("GET", "/ops/status"): AccessPolicy(Auth.REVIEW_TOKEN, None, False),
    ("POST", "/api/v1/auth/session"): AccessPolicy(
        Auth.PUBLIC,
        None,
        True,
        revalidates_in_transaction=False,
        public_reason=(
            "Password login must be reachable before a bearer session exists; "
            "validates supplied username/password."
        ),
        transaction_evidence=(
            "Public password login creates session and rate-limit records; no prior actor exists."
        ),
    ),
    ("DELETE", "/api/v1/auth/session"): AccessPolicy(
        Auth.USER_TOKEN,
        None,
        True,
        revalidates_in_transaction=True,
        auth_resolved_in_handler=True,
        auth_handler="app.api.v1.routes.auth.logout",
        transaction_evidence=(
            "app.services.auth.revoke_session: locks and re-reads the presented "
            "session; permits idempotent revocation."
        ),
    ),
    ("GET", "/api/v1/auth/me"): AccessPolicy(Auth.USER_TOKEN, None, False),
    ("GET", "/api/v1/auth/classes"): AccessPolicy(Auth.USER_TOKEN, None, False),
    ("GET", "/api/v1/auth/devices"): AccessPolicy(Auth.USER_TOKEN, None, False),
    ("GET", "/api/v1/auth/devices/{device_id}/dashboard"): AccessPolicy(
        Auth.USER_TOKEN,
        "intervention.manage | assignment.read",
        False,
        permission_checked_in_service=True,
        access_notes=(
            "Active-session scope: admin bypasses class capability; teacher needs "
            "intervention.manage, original student needs assignment.read/enrollment. "
            "No-session device access follows _accessible_devices role/binding scope."
        ),
    ),
    ("GET", "/api/v1/health"): AccessPolicy(
        Auth.PUBLIC,
        None,
        False,
        public_reason="Public service health probe (root and versioned aliases).",
    ),
    ("GET", "/api/v1/health/live"): AccessPolicy(
        Auth.PUBLIC,
        None,
        False,
        public_reason="Public service health probe (root and versioned aliases).",
    ),
    ("GET", "/api/v1/health/ready"): AccessPolicy(
        Auth.PUBLIC,
        None,
        False,
        public_reason="Public service health probe (root and versioned aliases).",
    ),
    ("GET", "/api/v1/health/dependencies"): AccessPolicy(
        Auth.PUBLIC,
        None,
        False,
        public_reason="Public service health probe (root and versioned aliases).",
    ),
    ("GET", "/api/v1/ops/status"): AccessPolicy(Auth.REVIEW_TOKEN, None, False),
    ("GET", "/api/v1/knowledge/case-drafts/pending"): AccessPolicy(
        Auth.USER_TOKEN,
        None,
        False,
        roles=("formal_approver", "teacher"),
        access_notes=(
            "Pending reads require reviewer role and recorded scope, with no "
            "additional capability check; writes use authorize_case_write."
        ),
    ),
    ("POST", "/api/v1/knowledge/case-drafts/{draft_id}/ai-polish"): AccessPolicy(
        Auth.USER_TOKEN,
        "knowledge.review.approve | intervention.manage",
        True,
        revalidates_in_transaction=True,
        roles=("formal_approver", "teacher"),
        permission_checked_in_service=True,
        access_notes=(
            "Formal approver uses knowledge.review.approve; teacher uses "
            "intervention.manage and recorded classroom scope."
        ),
        transaction_evidence=(
            "app.knowledge.case_drafting.apply_ai_assisted_polish: "
            "_authorize_final_case_write before commit."
        ),
    ),
    ("POST", "/api/v1/knowledge/case-drafts/{draft_id}/approve"): AccessPolicy(
        Auth.USER_TOKEN,
        "knowledge.review.approve | intervention.manage",
        True,
        revalidates_in_transaction=True,
        roles=("formal_approver", "teacher"),
        permission_checked_in_service=True,
        access_notes=(
            "Formal approver uses knowledge.review.approve; teacher uses "
            "intervention.manage and recorded classroom scope."
        ),
        transaction_evidence=(
            "app.knowledge.case_drafting.approve_case_draft: "
            "_authorize_final_case_write before commit."
        ),
    ),
    ("POST", "/api/v1/knowledge/cases/{case_id}/withdraw"): AccessPolicy(
        Auth.USER_TOKEN,
        "knowledge.review.approve | intervention.manage",
        True,
        revalidates_in_transaction=True,
        roles=("formal_approver", "teacher"),
        permission_checked_in_service=True,
        access_notes=(
            "Formal approver uses knowledge.review.approve; teacher uses "
            "intervention.manage and recorded classroom scope."
        ),
        transaction_evidence=(
            "app.knowledge.case_drafting.withdraw_case: authorize_case_write after case lock."
        ),
    ),
    ("POST", "/api/v1/teacher-workflow/diagnoses/{diagnosis_id}/intervention"): AccessPolicy(
        Auth.USER_TOKEN,
        "intervention.manage | assignment.read",
        True,
        revalidates_in_transaction=True,
        permission_checked_in_service=True,
        access_notes=(
            "_accessible_class_for_diagnosis: admin class scope bypasses capability; "
            "teacher needs intervention.manage, original student needs assignment.read."
        ),
        transaction_evidence=(
            "app.services.interventions.ensure_intervention_case: shared diagnosis lock then "
            "_authorize_intervention_request (current actor and recorded session/class) "
            "before flush; authorization locks held through route commit."
        ),
    ),
    ("GET", "/api/v1/teacher-workflow/interventions"): AccessPolicy(
        Auth.USER_TOKEN, "intervention.manage", False
    ),
    ("POST", "/api/v1/teacher-workflow/interventions/{case_id}/problem-resolution"): AccessPolicy(
        Auth.USER_TOKEN,
        "intervention.manage",
        True,
        revalidates_in_transaction=True,
        transaction_evidence=(
            "app.services.interventions.apply_problem_resolution: "
            "authorize_teacher_class after domain locks."
        ),
    ),
    ("GET", "/api/v1/teacher-workflow/interventions/{case_id}"): AccessPolicy(
        Auth.USER_TOKEN,
        "intervention.manage | assignment.read",
        False,
        permission_checked_in_service=True,
        access_notes=(
            "_assert_case_access: admin class scope bypasses capability; teacher "
            "needs intervention.manage, original student needs assignment.read."
        ),
    ),
    ("POST", "/api/v1/teacher-workflow/interventions/{case_id}/actions"): AccessPolicy(
        Auth.USER_TOKEN,
        "intervention.manage",
        True,
        revalidates_in_transaction=True,
        transaction_evidence=(
            "app.services.interventions.apply_action: authorize_teacher_class after domain locks."
        ),
    ),
    ("GET", "/api/v1/teacher-workflow/interventions/{case_id}/timeline"): AccessPolicy(
        Auth.USER_TOKEN, "intervention.manage", False
    ),
    ("POST", "/api/v1/teacher-workflow/messages"): AccessPolicy(
        Auth.USER_TOKEN,
        "intervention.manage",
        True,
        revalidates_in_transaction=True,
        transaction_evidence=(
            "Handler calls app.services.data_scope.authorize_teacher_class in the "
            "message write transaction."
        ),
    ),
    ("DELETE", "/api/v1/teacher-workflow/messages/{message_id}"): AccessPolicy(
        Auth.USER_TOKEN,
        "intervention.manage",
        True,
        revalidates_in_transaction=True,
        transaction_evidence=(
            "Handler calls app.services.data_scope.authorize_teacher_class in the "
            "message write transaction."
        ),
    ),
    ("GET", "/api/v1/teacher-workflow/classes/{class_id}/report.csv"): AccessPolicy(
        Auth.USER_TOKEN,
        "intervention.manage",
        True,
        revalidates_in_transaction=True,
        transaction_evidence=(
            "app.api.v1.routes.interventions.export_class_report: authorize_teacher_class "
            "before export audit; grants locked through audit commit; no CSV on denial."
        ),
    ),
    ("GET", "/api/v1/readiness/status"): AccessPolicy(
        Auth.PUBLIC,
        None,
        False,
        public_reason=(
            "Public aggregate readiness indicators; no account credentials or "
            "classroom records returned."
        ),
    ),
    ("POST", "/api/v1/device/ingest"): AccessPolicy(
        Auth.DEVICE_TOKEN,
        None,
        True,
        revalidates_in_transaction=True,
        transaction_evidence=(
            "app.services.device_ingest.lock_ingestion_device: re-reads active "
            "device/hash under write lock."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("DELETE", "/api/v1/device/test-runs/{test_run_id}"): AccessPolicy(
        Auth.DEVICE_TOKEN,
        None,
        True,
        revalidates_in_transaction=True,
        transaction_evidence=(
            "app.services.device_ingest.cleanup_test_run -> lock_ingestion_device."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("POST", "/api/v1/device/logs"): AccessPolicy(
        Auth.DEVICE_TOKEN,
        None,
        True,
        revalidates_in_transaction=True,
        transaction_evidence=(
            "app.services.device_ingest.ingest_legacy_record -> lock_ingestion_device"
            " before save_log commit."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("POST", "/api/v1/device/readings"): AccessPolicy(
        Auth.DEVICE_TOKEN,
        None,
        True,
        revalidates_in_transaction=True,
        transaction_evidence=(
            "app.services.device_ingest.ingest_legacy_record -> lock_ingestion_device"
            " before save_reading commit."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("POST", "/api/v1/device/heartbeat"): AccessPolicy(
        Auth.DEVICE_TOKEN,
        None,
        True,
        revalidates_in_transaction=True,
        transaction_evidence=(
            "app.services.device_ingest.ingest_legacy_record -> lock_ingestion_device"
            " before save_heartbeat commit."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("GET", "/api/v1/device/{device_id}/status"): AccessPolicy(
        Auth.DEVICE_TOKEN, None, False,
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("POST", "/api/v1/diagnosis/devices/{device_id}/run"): AccessPolicy(
        Auth.STUDENT_ACTOR,
        "dashboard.read & assignment.read",
        True,
        revalidates_in_transaction=True,
        permission_checked_in_service=True,
        access_notes=(
            "Account capability and recorded student/session/device scope; device "
            "credentials only for explicit demo scope. Account scope also requires "
            "assignment.read and student role; demo scope follows is_demo_session."
        ),
        transaction_evidence=(
            "app.services.diagnosis.save_diagnosis_result: student_actor passed by route; "
            "authorize_student_actor before source lock/flush, held through result commit."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("POST", "/api/v1/diagnosis/results/{diagnosis_result_id}/guidance"): AccessPolicy(
        Auth.STUDENT_ACTOR,
        "dashboard.read & assignment.read",
        True,
        revalidates_in_transaction=True,
        permission_checked_in_service=True,
        access_notes=(
            "Account capability and recorded student/session/device scope; device "
            "credentials only for explicit demo scope. Account scope also requires "
            "assignment.read and student role; demo scope follows is_demo_session."
        ),
        transaction_evidence=(
            "app.services.guidance.generate_guidance: authorize_student_actor inside "
            "lifecycle lock/write transaction."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("GET", "/api/v1/diagnosis/results/{diagnosis_result_id}/evidence"): AccessPolicy(
        Auth.STUDENT_ACTOR,
        "dashboard.read & assignment.read",
        False,
        permission_checked_in_service=True,
        access_notes=(
            "Account capability and recorded student/session/device scope; device "
            "credentials only for explicit demo scope. Account scope also requires "
            "assignment.read and student role; demo scope follows is_demo_session."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("GET", "/api/v1/diagnosis/ai/status"): AccessPolicy(
        Auth.PUBLIC,
        None,
        False,
        public_reason="Public AI enabled/configured status; returns no API key.",
    ),
    ("POST", "/api/v1/diagnosis/results/{diagnosis_result_id}/ai-explanation"): AccessPolicy(
        Auth.STUDENT_ACTOR,
        "dashboard.read & assignment.read",
        True,
        revalidates_in_transaction=True,
        permission_checked_in_service=True,
        access_notes=(
            "Account capability and recorded student/session/device scope; device "
            "credentials only for explicit demo scope. Account scope also requires "
            "assignment.read and student role; demo scope follows is_demo_session."
        ),
        transaction_evidence=(
            "app.services.ai_diagnosis: _authorize_projection before each persisted "
            "result and after Provider I/O."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("GET", "/api/v1/diagnosis/devices/{device_id}/guidance"): AccessPolicy(
        Auth.STUDENT_ACTOR,
        "dashboard.read & assignment.read",
        False,
        permission_checked_in_service=True,
        access_notes=(
            "Account capability and recorded student/session/device scope; device "
            "credentials only for explicit demo scope. Account scope also requires "
            "assignment.read and student role; demo scope follows is_demo_session."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("GET", "/api/v1/diagnosis/interventions"): AccessPolicy(Auth.REVIEW_TOKEN, None, False),
    ("POST", "/api/v1/diagnosis-workflows/devices/{device_id}"): AccessPolicy(
        Auth.STUDENT_ACTOR,
        "dashboard.read & assignment.read",
        True,
        revalidates_in_transaction=True,
        permission_checked_in_service=True,
        access_notes=(
            "Account capability and recorded student/session/device scope; device "
            "credentials only for explicit demo scope. Account scope also requires "
            "assignment.read and student role; demo scope follows is_demo_session."
        ),
        transaction_evidence=(
            "app.services.diagnosis_workflow.start_workflow and graph terminal nodes "
            "reauthorize each write transaction."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("GET", "/api/v1/diagnosis-workflows/devices/{device_id}/latest"): AccessPolicy(
        Auth.STUDENT_ACTOR,
        "dashboard.read & assignment.read",
        False,
        permission_checked_in_service=True,
        access_notes=(
            "Account capability and recorded student/session/device scope; device "
            "credentials only for explicit demo scope. Account scope also requires "
            "assignment.read and student role; demo scope follows is_demo_session."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("GET", "/api/v1/diagnosis-workflows/devices/{device_id}/checks/latest"): AccessPolicy(
        Auth.STUDENT_ACTOR,
        "dashboard.read & assignment.read",
        False,
        permission_checked_in_service=True,
        access_notes=(
            "Account capability and recorded student/session/device scope; device "
            "credentials only for explicit demo scope. Account scope also requires "
            "assignment.read and student role; demo scope follows is_demo_session."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("GET", "/api/v1/diagnosis-workflows/review-queue/pending"): AccessPolicy(
        Auth.USER_TOKEN, "intervention.manage", False
    ),
    ("GET", "/api/v1/diagnosis-workflows/review-queue/recent"): AccessPolicy(
        Auth.USER_TOKEN, "intervention.manage", False
    ),
    ("GET", "/api/v1/diagnosis-workflows/metrics/summary"): AccessPolicy(
        Auth.USER_TOKEN, "intervention.manage", False
    ),
    ("GET", "/api/v1/diagnosis-workflows/{workflow_id}"): AccessPolicy(
        Auth.STUDENT_ACTOR,
        "dashboard.read & assignment.read",
        False,
        permission_checked_in_service=True,
        access_notes=(
            "Account capability and recorded student/session/device scope; device "
            "credentials only for explicit demo scope. Account scope also requires "
            "assignment.read and student role; demo scope follows is_demo_session."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("POST", "/api/v1/diagnosis-workflows/{workflow_id}/review"): AccessPolicy(
        Auth.USER_TOKEN,
        "intervention.manage",
        True,
        revalidates_in_transaction=True,
        transaction_evidence=(
            "app.services.diagnosis_workflow.review_workflow: reauthorize_write reacquires "
            "workflow lock and authorize_workflow_review after rollback/graph commits, "
            "before failure trace, terminal reconciliation and final synchronization."
        ),
    ),
    ("POST", "/api/v1/experiments/packages/validate"): AccessPolicy(
        Auth.USER_TOKEN, "assignment.manage", False
    ),
    ("POST", "/api/v1/experiments/packages/import"): AccessPolicy(
        Auth.USER_TOKEN,
        "assignment.manage",
        True,
        revalidates_in_transaction=True,
        transaction_evidence=(
            "app.services.experiment_packages.import_experiment_package: "
            "authorize_actor before writes/commit."
        ),
    ),
    ("GET", "/api/v1/experiments/package-versions"): AccessPolicy(
        Auth.USER_TOKEN, "assignment.manage", False
    ),
    ("POST", "/api/v1/experiments/package-versions/{version_id}/status"): AccessPolicy(
        Auth.USER_TOKEN,
        "assignment.manage",
        True,
        revalidates_in_transaction=True,
        roles=("admin",),
        permission_checked_in_service=True,
        access_notes=(
            "app.services.experiment_packages.transition_experiment_package checks "
            "assignment.manage and current admin role."
        ),
        transaction_evidence=(
            "app.services.experiment_packages.transition_experiment_package: "
            "authorize_actor and current admin role after version lock."
        ),
    ),
    ("POST", "/api/v1/experiments/templates"): AccessPolicy(
        Auth.USER_TOKEN,
        "assignment.manage",
        True,
        revalidates_in_transaction=True,
        transaction_evidence=(
            "app.services.experiment_templates.create_template: authorize_actor "
            "before writes/commit."
        ),
    ),
    ("POST", "/api/v1/experiments/templates/{template_id}/versions"): AccessPolicy(
        Auth.USER_TOKEN,
        "assignment.manage",
        True,
        revalidates_in_transaction=True,
        transaction_evidence=(
            "app.services.experiment_templates.create_template_version: "
            "authorize_actor after parent lock."
        ),
    ),
    ("PATCH", "/api/v1/experiments/template-versions/{version_id}"): AccessPolicy(
        Auth.USER_TOKEN,
        "assignment.manage",
        True,
        revalidates_in_transaction=True,
        transaction_evidence=(
            "app.services.experiment_templates.update_content -> _lock_version -> authorize_actor."
        ),
    ),
    ("POST", "/api/v1/experiments/template-versions/{version_id}/status"): AccessPolicy(
        Auth.USER_TOKEN,
        "assignment.manage",
        True,
        revalidates_in_transaction=True,
        transaction_evidence=(
            "app.services.experiment_templates.transition -> _lock_version -> authorize_actor."
        ),
    ),
    ("GET", "/api/v1/student/assignments"): AccessPolicy(
        Auth.USER_TOKEN,
        "assignment.read",
        False,
        permission_checked_in_service=True,
        access_notes=(
            "app.services.data_scope.assert_student_assignment_access requires "
            "student role, assignment.read and active enrollment."
        ),
    ),
    ("POST", "/api/v1/student/experiment-sessions"): AccessPolicy(
        Auth.USER_TOKEN,
        "assignment.read",
        True,
        revalidates_in_transaction=True,
        permission_checked_in_service=True,
        access_notes=(
            "app.services.experiment_sessions.start_session uses assignment.read and "
            "current enrolled student scope."
        ),
        transaction_evidence=(
            "app.services.experiment_sessions.start_session: _command_lock and "
            "protect_student_scope before _record commit."
        ),
    ),
    ("POST", "/api/v1/student/experiment-sessions/{session_id}/end"): AccessPolicy(
        Auth.USER_TOKEN,
        "assignment.read",
        True,
        revalidates_in_transaction=True,
        permission_checked_in_service=True,
        access_notes=(
            "app.services.experiment_sessions.end_session uses assignment.read and "
            "original student scope."
        ),
        transaction_evidence=(
            "app.services.experiment_sessions.end_session: _command_lock and current "
            "scope before _record commit."
        ),
    ),
    ("GET", "/api/v1/student/experiment-sessions"): AccessPolicy(
        Auth.USER_TOKEN,
        "assignment.read",
        False,
        permission_checked_in_service=True,
        access_notes=(
            "app.services.data_scope.assert_student_session_access checks "
            "assignment.read and original student scope."
        ),
    ),
    ("POST", "/api/v1/student/session"): AccessPolicy(
        Auth.STUDENT_ACTOR,
        "dashboard.read & assignment.read",
        False,
        permission_checked_in_service=True,
        access_notes=(
            "Account capability and recorded student/session/device scope; device "
            "credentials only for explicit demo scope. Account scope also requires "
            "assignment.read and student role; demo scope follows is_demo_session."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("GET", "/api/v1/student/dashboard"): AccessPolicy(
        Auth.STUDENT_ACTOR,
        "dashboard.read & assignment.read",
        False,
        permission_checked_in_service=True,
        access_notes=(
            "Account capability and recorded student/session/device scope; device "
            "credentials only for explicit demo scope. Account scope also requires "
            "assignment.read and student role; demo scope follows is_demo_session."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("POST", "/api/v1/student/diagnoses/{diagnosis_result_id}/feedback"): AccessPolicy(
        Auth.STUDENT_ACTOR,
        "feedback.create & dashboard.read & assignment.read",
        True,
        revalidates_in_transaction=True,
        permission_checked_in_service=True,
        access_notes=(
            "Account capability and recorded student/session/device scope; device "
            "credentials only for explicit demo scope. Account scope also requires "
            "assignment.read and student role; demo scope follows is_demo_session."
        ),
        transaction_evidence=(
            "app.services.student_feedback.submit_student_feedback: "
            "authorize_student_actor before final commit."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("GET", "/api/v1/student/feedback-recovery"): AccessPolicy(
        Auth.STUDENT_ACTOR,
        "dashboard.read & assignment.read",
        False,
        permission_checked_in_service=True,
        access_notes=(
            "Account capability and recorded student/session/device scope; device "
            "credentials only for explicit demo scope. Account scope also requires "
            "assignment.read and student role; demo scope follows is_demo_session."
        ),
        missing_credentials_status=422,
        missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
        missing_credentials_source="app.api.dependencies.get_authenticated_device",
    ),
    ("GET", "/api/v1/student/experiment-session-commands/{request_id}"): AccessPolicy(
        Auth.USER_TOKEN,
        "assignment.read | assignment.manage",
        False,
        permission_checked_in_service=True,
        access_notes=(
            "Original student receipt uses assignment.read; managed receipt uses assignment.manage."
        ),
    ),
    ("POST", "/api/v1/student/diagnoses/{diagnosis_result_id}/queries"): AccessPolicy(
        Auth.STUDENT_ACTOR,
        "dashboard.read & assignment.read",
        True,
        revalidates_in_transaction=True,
        permission_checked_in_service=True,
        access_notes=(
            "Account capability and recorded student/session/device scope; device "
            "credentials only for explicit demo scope. Account scope also requires "
            "assignment.read and student role; demo scope follows is_demo_session."
        ),
        transaction_evidence="app.services.query_tasks.start_query: _authorize before task commit.",
    ),
    ("GET", "/api/v1/student/queries/{task_id}"): AccessPolicy(
        Auth.STUDENT_ACTOR,
        "dashboard.read & assignment.read",
        True,
        revalidates_in_transaction=True,
        permission_checked_in_service=True,
        access_notes=(
            "Account capability and recorded student/session/device scope; device "
            "credentials only for explicit demo scope. Account scope also requires "
            "assignment.read and student role; demo scope follows is_demo_session."
        ),
        transaction_evidence=(
            "app.services.query_tasks.read_query -> _deliver: _authorize before "
            "committing stale task/question state."
        ),
    ),
    ("GET", "/api/v1/student/diagnoses/{diagnosis_result_id}/queries"): AccessPolicy(
        Auth.STUDENT_ACTOR,
        "dashboard.read & assignment.read",
        False,
        permission_checked_in_service=True,
        access_notes=(
            "Account capability and recorded student/session/device scope; device "
            "credentials only for explicit demo scope. Account scope also requires "
            "assignment.read and student role; demo scope follows is_demo_session."
        ),
    ),
    ("POST", "/api/v1/student/queries/{task_id}/answers"): AccessPolicy(
        Auth.STUDENT_ACTOR,
        "feedback.create & dashboard.read & assignment.read",
        True,
        revalidates_in_transaction=True,
        permission_checked_in_service=True,
        access_notes=(
            "Account capability and recorded student/session/device scope; device "
            "credentials only for explicit demo scope. Account scope also requires "
            "assignment.read and student role; demo scope follows is_demo_session."
        ),
        transaction_evidence=(
            "app.services.query_tasks.submit_answer: _authorize(feedback.create) "
            "before receipt commit."
        ),
    ),
    ("GET", "/api/v1/teacher/dashboard"): AccessPolicy(
        Auth.USER_TOKEN,
        "dashboard.read",
        False,
        roles=("admin", "teacher"),
        permission_checked_in_service=True,
        access_notes=(
            "build_teacher_dashboard -> get_global_knowledge_status -> "
            "authorize_actor(dashboard.read); teacher devices/classes remain scoped."
        ),
    ),
    ("GET", "/api/v1/teacher/experiment-sessions"): AccessPolicy(
        Auth.USER_TOKEN,
        "assignment.manage",
        False,
        roles=("admin", "teacher"),
        permission_checked_in_service=True,
        access_notes=(
            "app.services.experiment_sessions._management_roles requires "
            "assignment.manage and teacher/admin classroom scope."
        ),
    ),
    ("POST", "/api/v1/teacher/experiment-sessions/{session_id}/release"): AccessPolicy(
        Auth.USER_TOKEN,
        "assignment.manage",
        True,
        revalidates_in_transaction=True,
        roles=("admin", "teacher"),
        permission_checked_in_service=True,
        access_notes=(
            "app.services.experiment_sessions.release_session requires "
            "assignment.manage and current teacher/admin classroom scope."
        ),
        transaction_evidence=(
            "app.services.experiment_sessions.release_session: _command_lock and "
            "authorize_teacher_class after locks."
        ),
    ),
    ("GET", "/api/v1/teacher/experiment-sessions/{session_id}"): AccessPolicy(
        Auth.USER_TOKEN,
        "assignment.manage",
        False,
        roles=("admin", "teacher"),
        permission_checked_in_service=True,
        access_notes=(
            "app.services.experiment_sessions.assert_session_management requires "
            "assignment.manage and teacher/admin classroom scope."
        ),
    ),
    ("GET", "/api/v1/memory/events"): AccessPolicy(
        Auth.USER_TOKEN,
        "intervention.manage",
        False,
        roles=("admin", "teacher"),
        permission_checked_in_service=True,
        access_notes=(
            "Memory governance checks current manager or recorded diagnosis classroom"
            " scope in service."
        ),
    ),
    ("GET", "/api/v1/memory/events/{event_id}/impacts"): AccessPolicy(
        Auth.USER_TOKEN,
        "intervention.manage",
        False,
        roles=("admin", "teacher"),
        permission_checked_in_service=True,
        access_notes=(
            "Memory governance checks current manager or recorded diagnosis classroom"
            " scope in service."
        ),
    ),
    ("POST", "/api/v1/memory/events/{event_id}/impacts/{diagnosis_id}/review"): AccessPolicy(
        Auth.USER_TOKEN,
        "intervention.manage",
        True,
        revalidates_in_transaction=True,
        roles=("admin", "teacher"),
        permission_checked_in_service=True,
        access_notes=(
            "Memory governance checks current manager or recorded diagnosis classroom"
            " scope in service."
        ),
        transaction_evidence=(
            "app.services.memory_governance.review_impact: can_review_diagnosis after event lock."
        ),
    ),
    ("POST", "/api/v1/memory/events/{event_id}/clear-caches"): AccessPolicy(
        Auth.USER_TOKEN,
        "user.manage",
        True,
        revalidates_in_transaction=True,
        roles=("admin",),
        permission_checked_in_service=True,
        access_notes=(
            "Memory governance checks current manager or recorded diagnosis classroom"
            " scope in service."
        ),
        transaction_evidence=(
            "app.services.memory_governance.process_stop_cache: require_manager after cache locks."
        ),
    ),
    ("POST", "/api/v1/memory/cleanup-plans"): AccessPolicy(
        Auth.USER_TOKEN,
        "user.manage",
        True,
        revalidates_in_transaction=True,
        roles=("admin",),
        permission_checked_in_service=True,
        access_notes=(
            "Memory governance checks current manager or recorded diagnosis classroom"
            " scope in service."
        ),
        transaction_evidence=(
            "app.services.memory_governance.plan_cleanup: require_manager in plan "
            "write transaction."
        ),
    ),
    ("GET", "/api/v1/memory/cleanup-plans/{plan_id}"): AccessPolicy(
        Auth.USER_TOKEN,
        "user.manage",
        False,
        roles=("admin",),
        permission_checked_in_service=True,
        access_notes=(
            "Memory governance checks current manager or recorded diagnosis classroom"
            " scope in service."
        ),
    ),
    ("POST", "/api/v1/memory/cleanup-plans/{plan_id}/execute"): AccessPolicy(
        Auth.USER_TOKEN,
        "user.manage",
        True,
        revalidates_in_transaction=True,
        roles=("admin",),
        permission_checked_in_service=True,
        access_notes=(
            "Memory governance checks current manager or recorded diagnosis classroom"
            " scope in service."
        ),
        transaction_evidence=(
            "app.services.memory_governance.execute_cleanup: require_manager after "
            "plan/cache locks."
        ),
    ),
    ("GET", "/api/v1/memory/events/{event_id}/package-candidates"): AccessPolicy(
        Auth.USER_TOKEN,
        "user.manage",
        False,
        roles=("admin",),
        permission_checked_in_service=True,
        access_notes=(
            "Memory governance checks current manager or recorded diagnosis classroom"
            " scope in service."
        ),
    ),
    ("GET", "/api/v1/memory/events/{event_id}/impacts/{diagnosis_id}/history"): AccessPolicy(
        Auth.USER_TOKEN,
        "intervention.manage",
        False,
        roles=("admin", "teacher"),
        permission_checked_in_service=True,
        access_notes=(
            "Memory governance checks current manager or recorded diagnosis classroom"
            " scope in service."
        ),
    ),
}
