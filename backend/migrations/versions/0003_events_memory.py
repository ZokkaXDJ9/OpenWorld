"""Event pipeline, reversible mutations and individual memory provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "messages", sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
    )
    if op.get_bind().dialect.name == "sqlite":
        # Rebuilding messages would cascade-delete existing knowledge through its source FK.
        op.execute(
            "ALTER TABLE messages ADD COLUMN speaker_character_id VARCHAR(36) "
            "REFERENCES characters(id) ON DELETE SET NULL"
        )
    else:
        op.add_column(
            "messages",
            sa.Column(
                "speaker_character_id",
                sa.String(36),
                sa.ForeignKey("characters.id", name="fk_message_speaker", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    # Existing role/identity data is retained; only the known assistant identity is backfilled.
    op.execute(
        sa.text(
            "UPDATE messages SET speaker_character_id = "
            "(SELECT character_id FROM conversations "
            "WHERE conversations.id = messages.conversation_id) "
            "WHERE role = 'assistant'"
        )
    )
    create_event_tables()
    with op.batch_alter_table("knowledge") as batch:
        batch.add_column(
            sa.Column("status", sa.String(20), nullable=False, server_default="active")
        )
        batch.add_column(
            sa.Column("origin", sa.String(30), nullable=False, server_default="legacy")
        )
        batch.add_column(sa.Column("event_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("subject_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("importance", sa.Integer(), nullable=False, server_default="50"))
        batch.add_column(sa.Column("emotion", sa.String(200), nullable=False, server_default=""))
        batch.create_foreign_key(
            "fk_knowledge_event", "events", ["event_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_foreign_key(
            "fk_knowledge_subject", "characters", ["subject_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_index("ix_knowledge_event_id", ["event_id"])
        batch.create_index("ix_knowledge_subject_id", ["subject_id"])
    op.create_table(
        "knowledge_links",
        sa.Column(
            "source_id",
            sa.String(36),
            sa.ForeignKey("knowledge.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "target_id",
            sa.String(36),
            sa.ForeignKey("knowledge.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("relation", sa.String(30), primary_key=True),
    )
    op.create_index("ix_knowledge_links_target_id", "knowledge_links", ["target_id"])


def create_event_tables():
    def col(name, kind, **kwargs):
        return sa.Column(name, kind, nullable=False, **kwargs)

    def ref(name, table, nullable=False, primary_key=False, ondelete="CASCADE"):
        return sa.Column(
            name,
            sa.String(36),
            sa.ForeignKey(f"{table}.id", ondelete=ondelete),
            nullable=nullable,
            primary_key=primary_key,
        )

    def identity():
        return sa.Column("id", sa.String(36), primary_key=True)

    def table(name, *columns, indexes=()):
        op.create_table(name, *columns)
        for column in indexes:
            op.create_index(f"ix_{name}_{column}", name, [column])

    table(
        "events",
        identity(),
        ref("world_id", "worlds"),
        col("event_type", sa.String(100)),
        col("description", sa.Text()),
        col("occurred_at", sa.DateTime(timezone=True)),
        col("created_at", sa.DateTime(timezone=True)),
        col("source", sa.String(30)),
        col("status", sa.String(30)),
        col("confidence", sa.Integer()),
        ref("location_id", "locations", nullable=True, ondelete="SET NULL"),
        col("revision", sa.Integer()),
        indexes=("world_id", "event_type", "occurred_at", "status", "location_id"),
    )
    table(
        "event_participants",
        ref("event_id", "events", primary_key=True),
        ref("character_id", "characters", primary_key=True),
        indexes=("character_id",),
    )
    table(
        "event_sources",
        identity(),
        ref("event_id", "events"),
        ref("message_id", "messages", nullable=True, ondelete="SET NULL"),
        col("message_revision", sa.Integer()),
        ref("conversation_id", "conversations", nullable=True, ondelete="SET NULL"),
        ref("speaker_character_id", "characters", nullable=True, ondelete="SET NULL"),
        col("role", sa.String(20)),
        col("quote", sa.Text()),
        indexes=("event_id", "message_id", "conversation_id"),
    )
    table(
        "event_proposals",
        identity(),
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        col("operations", sa.JSON()),
        col("preview", sa.JSON()),
        col("mode", sa.String(20)),
        col("reason", sa.Text()),
    )
    table(
        "event_targets",
        identity(),
        ref("event_id", "events"),
        col("entity_type", sa.String(30)),
        col("entity_id", sa.String(36)),
        sa.UniqueConstraint("event_id", "entity_type", "entity_id"),
        indexes=("event_id", "entity_type", "entity_id"),
    )
    table(
        "event_mutations",
        identity(),
        ref("event_id", "events"),
        col("sequence", sa.Integer()),
        col("entity_type", sa.String(30)),
        col("entity_id", sa.String(36)),
        col("before", sa.JSON()),
        col("after", sa.JSON()),
        col("revision_before", sa.Integer()),
        col("revision_after", sa.Integer()),
        col("reverted", sa.Boolean()),
        indexes=("event_id", "entity_type", "entity_id"),
    )
    table(
        "event_audit",
        identity(),
        ref("event_id", "events"),
        col("action", sa.String(30)),
        col("sequence", sa.Integer()),
        col("actor", sa.String(30)),
        col("detail", sa.JSON()),
        col("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("event_id", "sequence"),
        indexes=("event_id",),
    )
    table(
        "event_rules",
        identity(),
        ref("world_id", "worlds"),
        col("event_type", sa.String(100)),
        col("object_class", sa.String(30)),
        col("mode", sa.String(20)),
        col("revision", sa.Integer()),
        sa.UniqueConstraint("world_id", "event_type", "object_class"),
        indexes=("world_id",),
    )
    table(
        "extraction_jobs",
        identity(),
        ref("world_id", "worlds"),
        ref("conversation_id", "conversations", nullable=True, ondelete="SET NULL"),
        ref("message_id", "messages", nullable=True, ondelete="SET NULL"),
        col("message_revision", sa.Integer()),
        sa.Column("dedup_key", sa.String(100), nullable=False, unique=True),
        col("status", sa.String(30)),
        col("attempts", sa.Integer()),
        col("error", sa.Text()),
        col("event_ids", sa.JSON()),
        col("created_at", sa.DateTime(timezone=True)),
        indexes=("world_id", "conversation_id", "message_id", "status"),
    )
    table(
        "event_settings",
        ref("world_id", "worlds", primary_key=True),
        col("enabled", sa.Boolean()),
        col("revision", sa.Integer()),
    )


def downgrade():
    op.drop_table("knowledge_links")
    with op.batch_alter_table("knowledge") as batch:
        batch.drop_index("ix_knowledge_event_id")
        batch.drop_index("ix_knowledge_subject_id")
        batch.drop_constraint("fk_knowledge_event", type_="foreignkey")
        batch.drop_constraint("fk_knowledge_subject", type_="foreignkey")
        for column in (
            "status",
            "origin",
            "event_id",
            "subject_id",
            "occurred_at",
            "importance",
            "emotion",
        ):
            batch.drop_column(column)
    for table in (
        "event_settings",
        "extraction_jobs",
        "event_rules",
        "event_audit",
        "event_mutations",
        "event_targets",
        "event_proposals",
        "event_sources",
        "event_participants",
        "events",
    ):
        op.drop_table(table)
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_message_speaker", "messages", type_="foreignkey")
    op.drop_column("messages", "speaker_character_id")
    op.drop_column("messages", "revision")
