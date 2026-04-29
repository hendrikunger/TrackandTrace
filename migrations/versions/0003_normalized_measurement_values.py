"""Normalize measurement values

Revision ID: 0003_measurement_values
Revises: 0002_companion_contracts
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_measurement_values"
down_revision: str | None = "0002_companion_contracts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MEASUREMENT_TYPES = ("aussenring", "innenring", "breite", "ueberstand")


def upgrade() -> None:
    op.create_table(
        "measurement_values",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("measurement_id", sa.BigInteger(), nullable=False),
        sa.Column("measurement_type", sa.String(length=80), nullable=False),
        sa.Column("value", sa.Numeric(12, 4), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("result_status", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(["measurement_id"], ["measurements.id"]),
    )
    for measurement_type in MEASUREMENT_TYPES:
        op.execute(
            f"""
            insert into measurement_values (
                measurement_id,
                measurement_type,
                value,
                unit,
                result_status
            )
            select
                id,
                '{measurement_type}',
                {measurement_type},
                'mm',
                result_status
            from measurements
            where {measurement_type} is not null
            """
        )

    for measurement_type in MEASUREMENT_TYPES:
        op.drop_column("measurements", measurement_type)


def downgrade() -> None:
    for measurement_type in MEASUREMENT_TYPES:
        op.add_column(
            "measurements",
            sa.Column(measurement_type, sa.Numeric(12, 4), nullable=True),
        )
        op.execute(
            f"""
            update measurements
            set {measurement_type} = mv.value
            from measurement_values as mv
            where mv.measurement_id = measurements.id
              and mv.measurement_type = '{measurement_type}'
            """
        )

    op.drop_table("measurement_values")
