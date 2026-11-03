"""Persist sibling order while preserving the existing location traversal."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "locations", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0")
    )
    locations = sa.table(
        "locations",
        sa.column("id", sa.String(36)),
        sa.column("world_id", sa.String(36)),
        sa.column("parent_id", sa.String(36)),
        sa.column("sort_order", sa.Integer()),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(locations.c.id, locations.c.world_id, locations.c.parent_id)
    ).fetchall()
    counts: dict[tuple[str, str | None], int] = {}
    for item_id, world_id, parent_id in rows:
        key = (world_id, parent_id)
        position = counts.get(key, 0)
        connection.execute(
            locations.update().where(locations.c.id == item_id).values(sort_order=position)
        )
        counts[key] = position + 1


def downgrade():
    op.drop_column("locations", "sort_order")
