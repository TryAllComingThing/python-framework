"""Quality remediation constraints and query indexes.

Revision ID: 1_quality_remediation
Revises: 0_baseline
Create Date: 2026-11-20
"""
from alembic import op

revision = "1_quality_remediation"
down_revision = "0_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_sf_file_records_size_positive",
        "sf_file_records",
        "size > 0",
    )
    op.create_check_constraint(
        "ck_sf_file_records_sha256",
        "sf_file_records",
        "sha256 ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_sf_file_cleanup_jobs_attempts",
        "sf_file_cleanup_jobs",
        "attempts >= 0",
    )
    op.create_check_constraint(
        "ck_sf_login_attempts_failures",
        "sf_login_attempts",
        "failures >= 0",
    )
    op.create_index(
        "ix_sf_file_cleanup_jobs_lease_created",
        "sf_file_cleanup_jobs",
        ["lease_until", "created_at"],
    )
    op.create_index(
        "ix_sf_file_cleanup_jobs_created",
        "sf_file_cleanup_jobs",
        ["created_at"],
    )
    op.create_index("ix_sf_audit_events_created_at", "sf_audit_events", ["created_at"])
    op.create_index("ix_sf_audit_events_actor_id", "sf_audit_events", ["actor_id"])
    op.create_index("ix_sf_audit_events_request_id", "sf_audit_events", ["request_id"])
    op.create_index("ix_sf_login_sessions_expires_at", "sf_login_sessions", ["expires_at"])
    op.create_index("ix_sf_login_sessions_revoked_at", "sf_login_sessions", ["revoked_at"])
    # Preflight:
    # SELECT lower(username), count(*) FROM sf_users GROUP BY 1 HAVING count(*) > 1;
    op.execute(
        "CREATE UNIQUE INDEX ix_sf_users_username_lower "
        "ON sf_users (lower(username))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sf_users_username_lower")
    op.drop_index("ix_sf_login_sessions_revoked_at", table_name="sf_login_sessions")
    op.drop_index("ix_sf_login_sessions_expires_at", table_name="sf_login_sessions")
    op.drop_index("ix_sf_audit_events_request_id", table_name="sf_audit_events")
    op.drop_index("ix_sf_audit_events_actor_id", table_name="sf_audit_events")
    op.drop_index("ix_sf_audit_events_created_at", table_name="sf_audit_events")
    op.drop_index("ix_sf_file_cleanup_jobs_created", table_name="sf_file_cleanup_jobs")
    op.drop_index(
        "ix_sf_file_cleanup_jobs_lease_created",
        table_name="sf_file_cleanup_jobs",
    )
    op.drop_constraint(
        "ck_sf_login_attempts_failures",
        "sf_login_attempts",
        type_="check",
    )
    op.drop_constraint(
        "ck_sf_file_cleanup_jobs_attempts",
        "sf_file_cleanup_jobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_sf_file_records_sha256",
        "sf_file_records",
        type_="check",
    )
    op.drop_constraint(
        "ck_sf_file_records_size_positive",
        "sf_file_records",
        type_="check",
    )
