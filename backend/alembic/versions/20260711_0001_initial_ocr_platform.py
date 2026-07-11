"""Create the asynchronous OCR platform schema.

Revision ID: 20260711_0001
Revises:
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260711_0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def uuid_pk() -> sa.Column:
    return sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()"))


def timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    op.create_table(
        "api_keys",
        uuid_pk(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("key_prefix", sa.String(24), nullable=False),
        sa.Column("key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("salt", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_api_keys_status"),
    )
    op.create_index("uq_api_keys_prefix", "api_keys", ["key_prefix"], unique=True)

    op.create_table(
        "upload_sessions",
        uuid_pk(),
        sa.Column("api_key_id", UUID, sa.ForeignKey("api_keys.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("declared_content_type", sa.String(160), nullable=False),
        sa.Column("detected_content_type", sa.String(160)),
        sa.Column("expected_sha256", sa.String(64), nullable=False),
        sa.Column("verified_sha256", sa.String(64)),
        sa.Column("expected_size", sa.BigInteger(), nullable=False),
        sa.Column("verified_size", sa.BigInteger()),
        sa.Column("multipart_upload_id", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_claim_token", UUID),
        sa.Column("retention_lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.CheckConstraint("expected_size > 0", name="ck_upload_sessions_size"),
        sa.CheckConstraint(
            "(retention_claim_token IS NULL) = (retention_lease_expires_at IS NULL)",
            name="ck_upload_sessions_retention_claim",
        ),
    )
    op.create_index("uq_upload_sessions_object_key", "upload_sessions", ["object_key"], unique=True)
    op.create_index("ix_upload_sessions_expiry", "upload_sessions", ["status", "expires_at"])

    op.create_table(
        "ocr_jobs",
        uuid_pk(),
        sa.Column("api_key_id", UUID, sa.ForeignKey("api_keys.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("upload_id", UUID, sa.ForeignKey("upload_sessions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(160)),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("current_attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_pages", sa.Integer()),
        sa.Column("completed_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("options", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_claim_token", UUID),
        sa.Column("retention_lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_internal_code", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_reason", sa.String(160)),
        *timestamps(),
        sa.CheckConstraint("current_attempt > 0", name="ck_ocr_jobs_attempt"),
        sa.CheckConstraint("completed_pages >= 0", name="ck_ocr_jobs_completed_pages"),
        sa.CheckConstraint("progress_percent >= 0 AND progress_percent <= 100", name="ck_ocr_jobs_progress"),
        sa.CheckConstraint(
            "(retention_claim_token IS NULL) = (retention_lease_expires_at IS NULL)",
            name="ck_ocr_jobs_retention_claim",
        ),
    )
    op.create_index(
        "uq_ocr_jobs_api_key_idempotency",
        "ocr_jobs",
        ["api_key_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_ocr_jobs_owner_created", "ocr_jobs", ["api_key_id", "created_at"])
    op.create_index("ix_ocr_jobs_cleanup", "ocr_jobs", ["status", "expires_at"])

    op.create_table(
        "ocr_job_attempts",
        uuid_pk(),
        sa.Column("job_id", UUID, sa.ForeignKey("ocr_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("engine_name", sa.String(80)),
        sa.Column("engine_version", sa.String(80)),
        sa.Column("model_name", sa.String(160)),
        sa.Column("error_details", JSONB),
        *timestamps(),
        sa.UniqueConstraint("job_id", "attempt", name="uq_ocr_job_attempts_job_attempt"),
    )

    op.create_table(
        "ocr_job_pages",
        uuid_pk(),
        sa.Column("job_id", UUID, sa.ForeignKey("ocr_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_object_key", sa.Text(), nullable=False),
        sa.Column("result_object_key", sa.Text()),
        sa.Column("visualization_object_key", sa.Text()),
        sa.Column("source_sha256", sa.String(64)),
        sa.Column("result_sha256", sa.String(64)),
        sa.Column("claimed_by", sa.String(160)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("last_internal_code", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_reason", sa.String(160)),
        *timestamps(),
        sa.CheckConstraint("page_number > 0", name="ck_ocr_job_pages_page_number"),
        sa.CheckConstraint("retry_count >= 0", name="ck_ocr_job_pages_retry_count"),
        sa.UniqueConstraint("job_id", "attempt", "page_number", name="uq_ocr_job_pages_checkpoint"),
    )
    op.create_index("ix_ocr_job_pages_claim", "ocr_job_pages", ["status", "lease_expires_at"])

    op.create_table(
        "ocr_artifacts",
        uuid_pk(),
        sa.Column("job_id", UUID, sa.ForeignKey("ocr_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer()),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(160), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("job_id", "attempt", "kind", "page_number", name="uq_ocr_artifacts_logical"),
    )
    op.create_index("ix_ocr_artifacts_job", "ocr_artifacts", ["job_id", "attempt"])

    op.create_table(
        "outbox_events",
        uuid_pk(),
        sa.Column("aggregate_type", sa.String(80), nullable=False),
        sa.Column("aggregate_id", UUID, nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("topic", sa.String(200), nullable=False),
        sa.Column("partition_key", sa.String(200), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("publish_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_outbox_events_unpublished", "outbox_events", ["created_at"], postgresql_where=sa.text("published_at IS NULL"))

    op.create_table(
        "job_events",
        sa.Column("job_id", UUID, sa.ForeignKey("ocr_jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("sequence", sa.BigInteger(), primary_key=True),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("internal_code", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    for table in (
        "job_events",
        "outbox_events",
        "ocr_artifacts",
        "ocr_job_pages",
        "ocr_job_attempts",
        "ocr_jobs",
        "upload_sessions",
        "api_keys",
    ):
        op.drop_table(table)
