"""Station diagnostics events

Revision ID: 0008_station_events
Revises: 0007_station_identity_cleanup
Create Date: 2026-05-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_station_events"
down_revision: str | None = "0007_station_identity_cleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "station_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("station_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"]),
    )
    op.create_index(
        "ix_station_events_station_occurred",
        "station_events",
        ["station_id", "occurred_at"],
    )
    op.create_index("ix_station_events_severity", "station_events", ["severity"])


def downgrade() -> None:
    op.drop_index("ix_station_events_severity", table_name="station_events")
    op.drop_index("ix_station_events_station_occurred", table_name="station_events")
    op.drop_table("station_events")
