"""Participant-scoped conversations, witnessed messages and bounded persistent simulations."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def add_reference(table: str, column: str, parent: str, ondelete: str):
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR(36) "
            f"REFERENCES {parent}(id) ON DELETE {ondelete}"
        )
    else:
        op.add_column(table, sa.Column(column, sa.String(36), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_{column}",
            table,
            parent,
            [column],
            ["id"],
            ondelete=ondelete,
        )


def drop_reference(table: str, column: str):
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(f"fk_{table}_{column}", table, type_="foreignkey")
    op.drop_column(table, column)


def upgrade():
    op.add_column("messages", sa.Column("world_minute", sa.Integer(), nullable=True))
    op.add_column("events", sa.Column("world_minute", sa.Integer(), nullable=True))
    op.add_column(
        "conversations", sa.Column("kind", sa.String(20), nullable=False, server_default="single")
    )
    op.add_column("conversations", sa.Column("scene", sa.Text(), nullable=False, server_default=""))
    add_reference("conversations", "scene_location_id", "locations", "RESTRICT")
    op.add_column(
        "conversations",
        sa.Column("communication", sa.String(30), nullable=False, server_default="in_person"),
    )
    op.add_column(
        "messages", sa.Column("speaker_type", sa.String(20), nullable=False, server_default="human")
    )
    op.execute(
        "UPDATE messages SET speaker_type = 'character' WHERE speaker_character_id IS NOT NULL"
    )
    op.create_table(
        "conversation_participants",
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "character_id",
            sa.String(36),
            sa.ForeignKey("characters.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.execute(
        "INSERT INTO conversation_participants SELECT id, character_id, 0, 1 FROM conversations"
    )
    op.create_table(
        "message_audience",
        sa.Column(
            "message_id",
            sa.String(36),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "character_id",
            sa.String(36),
            sa.ForeignKey("characters.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("perception", sa.String(20), nullable=False),
    )
    op.create_table(
        "world_clocks",
        sa.Column(
            "id", sa.String(36), sa.ForeignKey("worlds.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("elapsed_minutes", sa.Integer(), nullable=False),
        sa.Column("minutes_per_day", sa.Integer(), nullable=False),
        sa.Column("epoch_label", sa.String(200), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_table(
        "simulations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "world_id",
            sa.String(36),
            sa.ForeignKey("worlds.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        *[
            sa.Column(name, sa.Integer(), nullable=False)
            for name in (
                "max_rounds",
                "completed_rounds",
                "run_until",
                "max_calls",
                "calls_used",
                "max_tokens",
                "tokens_reserved",
                "timeout_seconds",
                "minutes_per_round",
                "revision",
            )
        ],
        sa.Column("seconds_used", sa.Float(), nullable=False),
        sa.Column("event_mode", sa.String(20), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("stop_reason", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_running_simulation_world",
        "simulations",
        ["world_id"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_table(
        "simulation_turns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "simulation_id",
            sa.String(36),
            sa.ForeignKey("simulations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column(
            "character_id",
            sa.String(36),
            sa.ForeignKey("characters.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.String(36),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column(
            "clock_event_id",
            sa.String(36),
            sa.ForeignKey("events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("simulation_id", "number"),
    )
    op.create_table(
        "simulation_dependencies",
        sa.Column(
            "turn_id",
            sa.String(36),
            sa.ForeignKey("simulation_turns.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            primary_key=True,
            index=True,
        ),
    )
    add_reference("event_sources", "recipient_id", "characters", "SET NULL")
    add_reference("extraction_jobs", "recipient_id", "characters", "CASCADE")
    add_reference("extraction_jobs", "simulation_id", "simulations", "CASCADE")
    op.add_column(
        "extraction_jobs",
        sa.Column("allow_auto_retry", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_extraction_jobs_simulation_id", "extraction_jobs", ["simulation_id"])


def downgrade():
    op.drop_column("messages", "world_minute")
    op.drop_column("events", "world_minute")
    op.drop_index("ix_extraction_jobs_simulation_id", table_name="extraction_jobs")
    drop_reference("extraction_jobs", "recipient_id")
    drop_reference("extraction_jobs", "simulation_id")
    op.drop_column("extraction_jobs", "allow_auto_retry")
    drop_reference("event_sources", "recipient_id")
    op.drop_table("simulation_dependencies")
    op.drop_table("simulation_turns")
    op.drop_table("simulations")
    op.drop_table("world_clocks")
    op.drop_table("message_audience")
    op.drop_table("conversation_participants")
    op.drop_column("messages", "speaker_type")
    drop_reference("conversations", "scene_location_id")
    for column in ("kind", "scene", "communication"):
        op.drop_column("conversations", column)
