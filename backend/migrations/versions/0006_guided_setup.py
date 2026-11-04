"""Guided connection checks and explicit memory controls."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "simulations",
        sa.Column("recognize_events", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "provider_settings",
        sa.Column("setup_state", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "event_settings",
        sa.Column("confirm_changes", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "event_settings",
        sa.Column("automation_disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("simulations", "recognize_events")
    op.drop_column("event_settings", "automation_disabled")
    op.drop_column("event_settings", "confirm_changes")
    op.drop_column("provider_settings", "setup_state")
