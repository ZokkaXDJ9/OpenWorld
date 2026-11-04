"""Independent extraction configuration, diagnostics and revision-bound turn sources."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "provider_settings",
        sa.Column("reasoning_profile", sa.String(30), nullable=False, server_default="default"),
    )
    op.add_column(
        "provider_settings",
        sa.Column("reasoning_mode", sa.String(20), nullable=False, server_default="default"),
    )
    op.add_column(
        "extraction_jobs",
        sa.Column("diagnostics", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_table(
        "extraction_job_sources",
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("extraction_jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "message_id",
            sa.String(36),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_extraction_job_sources_message_id", "extraction_job_sources", ["message_id"]
    )
    op.execute(
        "INSERT INTO extraction_job_sources (job_id, message_id, revision) "
        "SELECT id, message_id, message_revision FROM extraction_jobs "
        "WHERE message_id IN (SELECT id FROM messages)"
    )
    op.create_table(
        "extraction_provider_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("use_chat_connection", sa.Boolean(), nullable=False),
        sa.Column("base_url", sa.String(2000), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("provider_profile", sa.String(30), nullable=False),
        sa.Column("reasoning_mode", sa.String(20), nullable=False),
        sa.Column("structured_output", sa.String(20), nullable=False),
        sa.Column("auto_retry", sa.Boolean(), nullable=False),
    )


def downgrade():
    op.drop_table("extraction_provider_settings")
    op.drop_table("extraction_job_sources")
    op.drop_column("extraction_jobs", "diagnostics")
    op.drop_column("provider_settings", "reasoning_mode")
    op.drop_column("provider_settings", "reasoning_profile")
