"""Station companion tokens

Revision ID: 0010_station_companion_tokens
Revises: 0009_station_workflow_config
Create Date: 2026-05-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_station_companion_tokens"
down_revision: str | None = "0009_station_workflow_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stations", sa.Column("companion_token_hash", sa.String(length=80)))


def downgrade() -> None:
    op.drop_column("stations", "companion_token_hash")
