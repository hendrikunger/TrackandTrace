"""Measurement type catalog

Revision ID: 0004_measurement_catalog
Revises: 0003_measurement_values
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_measurement_catalog"
down_revision: str | None = "0003_measurement_values"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "measurement_types",
        sa.Column("code", sa.String(length=80), primary_key=True),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "station_measurement_types",
        sa.Column("station_id", sa.BigInteger(), nullable=False),
        sa.Column("measurement_type_code", sa.String(length=80), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"]),
        sa.ForeignKeyConstraint(["measurement_type_code"], ["measurement_types.code"]),
        sa.PrimaryKeyConstraint("station_id", "measurement_type_code"),
    )
    op.bulk_insert(
        sa.table(
            "measurement_types",
            sa.column("code", sa.String),
            sa.column("label", sa.String),
            sa.column("unit", sa.String),
            sa.column("active", sa.Boolean),
        ),
        [
            {"code": "aussenring", "label": "Außenring", "unit": "mm", "active": True},
            {"code": "innenring", "label": "Innenring", "unit": "mm", "active": True},
            {"code": "breite", "label": "Breite", "unit": "mm", "active": True},
            {"code": "ueberstand", "label": "Überstand", "unit": "mm", "active": True},
        ],
    )
    op.execute(
        """
        insert into station_measurement_types (station_id, measurement_type_code, active)
        select stations.id, measurement_types.code, true
        from stations
        cross join measurement_types
        """
    )
    op.create_foreign_key(
        "measurement_values_measurement_type_fkey",
        "measurement_values",
        "measurement_types",
        ["measurement_type"],
        ["code"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "measurement_values_measurement_type_fkey",
        "measurement_values",
        type_="foreignkey",
    )
    op.drop_table("station_measurement_types")
    op.drop_table("measurement_types")
