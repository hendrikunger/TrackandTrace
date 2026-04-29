"""Station adapter configuration

Revision ID: 0006_station_adapter_config
Revises: 0005_station_inventory
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_station_adapter_config"
down_revision: str | None = "0005_station_inventory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stations", sa.Column("adapter_config", sa.JSON()))


def downgrade() -> None:
    op.drop_column("stations", "adapter_config")
