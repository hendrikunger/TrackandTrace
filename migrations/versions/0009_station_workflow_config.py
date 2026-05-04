"""Station workflow config

Revision ID: 0009_station_workflow_config
Revises: 0008_station_events
Create Date: 2026-05-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_station_workflow_config"
down_revision: str | None = "0008_station_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stations",
        sa.Column(
            "workflow_type",
            sa.String(length=80),
            server_default="measurement_capture",
            nullable=False,
        ),
    )
    op.add_column("stations", sa.Column("workflow_title", sa.String(length=120)))
    op.add_column("stations", sa.Column("workflow_config", sa.JSON()))


def downgrade() -> None:
    op.drop_column("stations", "workflow_config")
    op.drop_column("stations", "workflow_title")
    op.drop_column("stations", "workflow_type")
