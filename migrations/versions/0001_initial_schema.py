"""Initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("machine_name", sa.String(length=255), nullable=True),
        sa.Column("machine_type", sa.String(length=120), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "parts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("rueckmeldenummer", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("rueckmeldenummer"),
    )
    op.create_table(
        "raw_payloads",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("station_id", sa.BigInteger(), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("payload_hash", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"]),
    )
    op.create_index("ix_raw_payloads_payload_hash", "raw_payloads", ["payload_hash"])
    op.create_table(
        "measurements",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("part_id", sa.BigInteger(), nullable=False),
        sa.Column("station_id", sa.BigInteger(), nullable=False),
        sa.Column("aussenring", sa.Numeric(12, 4), nullable=True),
        sa.Column("innenring", sa.Numeric(12, 4), nullable=True),
        sa.Column("breite", sa.Numeric(12, 4), nullable=True),
        sa.Column("ueberstand", sa.Numeric(12, 4), nullable=True),
        sa.Column("result_status", sa.String(length=40), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("raw_payload_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["part_id"], ["parts.id"]),
        sa.ForeignKeyConstraint(["raw_payload_id"], ["raw_payloads.id"]),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"]),
    )


def downgrade() -> None:
    op.drop_table("measurements")
    op.drop_index("ix_raw_payloads_payload_hash", table_name="raw_payloads")
    op.drop_table("raw_payloads")
    op.drop_table("parts")
    op.drop_table("stations")
