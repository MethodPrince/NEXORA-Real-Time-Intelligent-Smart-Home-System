"""add automation schedule runtime fields

Revision ID: 71c4a8d92ef1
Revises: b5c345a87291
Create Date: 2026-10-23 11:00:00.000000
"""

from typing import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "71c4a8d92ef1"
down_revision: Union[str, Sequence[str], None] = "b5c345a87291"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "automation_rules",
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "automation_rules",
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "automation_rules",
        sa.Column("last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("automation_rules", "last_error")
    op.drop_column("automation_rules", "last_run_at")
    op.drop_column("automation_rules", "next_run_at")
