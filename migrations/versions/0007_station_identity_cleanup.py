"""Station identity cleanup

Revision ID: 0007_station_identity_cleanup
Revises: 0006_station_adapter_config
Create Date: 2026-05-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_station_identity_cleanup"
down_revision: str | None = "0006_station_adapter_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("station_heartbeats", sa.Column("hostname", sa.String(length=255)))
    op.drop_column("stations", "measurement_interface")
    op.drop_column("stations", "operating_system")
    op.drop_column("stations", "machine_type")
    op.drop_column("stations", "machine_name")
    op.drop_column("stations", "hostname")


def downgrade() -> None:
    op.add_column("stations", sa.Column("hostname", sa.String(length=255)))
    op.add_column("stations", sa.Column("machine_name", sa.String(length=255)))
    op.add_column("stations", sa.Column("machine_type", sa.String(length=120)))
    op.add_column("stations", sa.Column("operating_system", sa.String(length=80)))
    op.add_column("stations", sa.Column("measurement_interface", sa.String(length=80)))
    op.drop_column("station_heartbeats", "hostname")
