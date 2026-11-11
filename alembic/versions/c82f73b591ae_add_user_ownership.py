"""add user ownership to home data

Revision ID: c82f73b591ae
Revises: 71c4a8d92ef1
Create Date: 2026-11-11 12:14:00.000000
"""

from typing import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "c82f73b591ae"
down_revision: Union[str, Sequence[str], None] = "71c4a8d92ef1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.add_column(sa.Column("owner_user_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_devices_owner_user_id_users",
            "users",
            ["owner_user_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_index(
        op.f("ix_devices_owner_user_id"),
        "devices",
        ["owner_user_id"],
        unique=False,
    )
    with op.batch_alter_table("automation_rules") as batch_op:
        batch_op.add_column(sa.Column("owner_user_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_automation_rules_owner_user_id_users",
            "users",
            ["owner_user_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_index(
        op.f("ix_automation_rules_owner_user_id"),
        "automation_rules",
        ["owner_user_id"],
        unique=False,
    )
    op.execute(
        sa.text(
            "UPDATE automation_rules SET enabled = false, next_run_at = NULL "
            "WHERE owner_user_id IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_automation_rules_owner_user_id"), table_name="automation_rules")
    with op.batch_alter_table("automation_rules") as batch_op:
        batch_op.drop_constraint("fk_automation_rules_owner_user_id_users", type_="foreignkey")
        batch_op.drop_column("owner_user_id")
    op.drop_index(op.f("ix_devices_owner_user_id"), table_name="devices")
    with op.batch_alter_table("devices") as batch_op:
        batch_op.drop_constraint("fk_devices_owner_user_id_users", type_="foreignkey")
        batch_op.drop_column("owner_user_id")
