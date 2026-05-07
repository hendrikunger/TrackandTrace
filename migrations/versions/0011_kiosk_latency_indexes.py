"""Kiosk latency indexes

Revision ID: 0011_kiosk_latency_indexes
Revises: 0010_station_companion_tokens
Create Date: 2026-05-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_kiosk_latency_indexes"
down_revision: str | None = "0010_station_companion_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_raw_payloads_station_source_received",
        "raw_payloads",
        ["station_id", "source_type", "received_at", "id"],
    )
    op.create_index(
        "ix_measurements_station_part_id",
        "measurements",
        ["station_id", "part_id", "id"],
    )
    op.create_index(
        "ix_measurements_station_measured",
        "measurements",
        ["station_id", "measured_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_measurements_station_measured", table_name="measurements")
    op.drop_index("ix_measurements_station_part_id", table_name="measurements")
    op.drop_index("ix_raw_payloads_station_source_received", table_name="raw_payloads")
