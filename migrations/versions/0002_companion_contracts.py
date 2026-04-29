"""Companion API contracts

Revision ID: 0002_companion_contracts
Revises: 0001_initial_schema
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_companion_contracts"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "station_heartbeats",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("station_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("companion_version", sa.String(length=80), nullable=True),
        sa.Column("adapter_status", sa.JSON(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"]),
    )
    op.add_column(
        "measurements",
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
    )
    op.execute(
        "update measurements set idempotency_key = 'legacy-' || id::text "
        "where idempotency_key is null"
    )
    op.alter_column("measurements", "idempotency_key", nullable=False)
    op.create_unique_constraint(
        "uq_measurements_station_idempotency",
        "measurements",
        ["station_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_measurements_station_idempotency",
        "measurements",
        type_="unique",
    )
    op.drop_column("measurements", "idempotency_key")
    op.drop_table("station_heartbeats")
