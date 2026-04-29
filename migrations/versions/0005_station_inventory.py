"""Station inventory fields

Revision ID: 0005_station_inventory
Revises: 0004_measurement_catalog
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_station_inventory"
down_revision: str | None = "0004_measurement_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stations", sa.Column("operating_system", sa.String(length=80)))
    op.add_column("stations", sa.Column("measurement_interface", sa.String(length=80)))
    op.add_column("stations", sa.Column("scanner_host", sa.String(length=255)))
    op.add_column("stations", sa.Column("scanner_port", sa.Integer()))
    op.add_column("stations", sa.Column("scanner_protocol", sa.String(length=80)))
    op.add_column("stations", sa.Column("payload_format", sa.Text()))
    op.add_column("stations", sa.Column("timing_notes", sa.Text()))
    op.add_column("stations", sa.Column("network_notes", sa.Text()))


def downgrade() -> None:
    op.drop_column("stations", "network_notes")
    op.drop_column("stations", "timing_notes")
    op.drop_column("stations", "payload_format")
    op.drop_column("stations", "scanner_protocol")
    op.drop_column("stations", "scanner_port")
    op.drop_column("stations", "scanner_host")
    op.drop_column("stations", "measurement_interface")
    op.drop_column("stations", "operating_system")
