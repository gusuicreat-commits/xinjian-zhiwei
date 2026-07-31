"""remove assistant and technical reviewer roles

Revision ID: 20260730_0015
Revises: 20260727_0014
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0015"
down_revision: str | None = "20260727_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()

    # A teaching assistant had the same classroom scope as a teacher. Preserve
    # existing access by moving those assignments to the teacher role.
    connection.execute(
        sa.text(
            """
            INSERT INTO user_roles (user_id, role_id)
            SELECT ur.user_id, teacher.id
            FROM user_roles AS ur
            JOIN roles AS old_role ON old_role.id = ur.role_id
            JOIN roles AS teacher ON teacher.code = 'teacher'
            WHERE old_role.code = 'teaching_assistant'
            ON CONFLICT DO NOTHING
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE knowledge_documents
            SET review_status = 'pending'
            WHERE review_status = 'technical_reviewed'
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE knowledge_chunks
            SET review_status = 'pending'
            WHERE review_status = 'technical_reviewed'
            """
        )
    )
    connection.execute(
        sa.text(
            """
            DELETE FROM roles
            WHERE code IN ('teaching_assistant', 'technical_reviewer')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            DELETE FROM permissions
            WHERE code = 'knowledge.review.technical'
              AND NOT EXISTS (
                  SELECT 1
                  FROM role_permissions
                  WHERE role_permissions.permission_id = permissions.id
              )
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    now = datetime.now(timezone.utc)
    roles = sa.table(
        "roles",
        sa.column("id", sa.String()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.String()),
        sa.column("code", sa.String()),
        sa.column("description", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.String()),
        sa.column("permission_id", sa.String()),
    )

    existing_roles = set(
        connection.execute(sa.text("SELECT code FROM roles")).scalars()
    )
    role_ids: dict[str, str] = {}
    for code, name in (
        ("teaching_assistant", "Teaching Assistant"),
        ("technical_reviewer", "Technical Reviewer"),
    ):
        if code not in existing_roles:
            role_id = str(uuid.uuid4())
            op.bulk_insert(
                roles,
                [
                    {
                        "id": role_id,
                        "code": code,
                        "name": name,
                        "created_at": now,
                        "updated_at": now,
                    }
                ],
            )
            role_ids[code] = role_id
        else:
            role_ids[code] = connection.execute(
                sa.text("SELECT id FROM roles WHERE code = :code"),
                {"code": code},
            ).scalar_one()

    permission_id = connection.execute(
        sa.text(
            "SELECT id FROM permissions WHERE code = 'knowledge.review.technical'"
        )
    ).scalar_one_or_none()
    if permission_id is None:
        permission_id = str(uuid.uuid4())
        op.bulk_insert(
            permissions,
            [
                {
                    "id": permission_id,
                    "code": "knowledge.review.technical",
                    "description": "RBAC permission: knowledge.review.technical",
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        )
    op.bulk_insert(
        role_permissions,
        [
            {
                "role_id": role_ids["technical_reviewer"],
                "permission_id": permission_id,
            }
        ],
    )
