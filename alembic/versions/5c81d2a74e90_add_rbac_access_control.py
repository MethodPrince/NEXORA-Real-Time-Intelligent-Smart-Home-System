"""add role-based access and explicit device grants

Revision ID: 5c81d2a74e90
Revises: c82f73b591ae
Create Date: 2026-11-11 12:47:00.000000
"""

from typing import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "5c81d2a74e90"
down_revision: Union[str, Sequence[str], None] = "c82f73b591ae"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE user_role RENAME VALUE 'HOME_USER' TO 'STANDARD_USER'")
        op.execute(
            "UPDATE users SET role = 'STANDARD_USER' WHERE role = 'SYSTEM'"
        )
    else:
        op.execute(
            "UPDATE users SET role = 'STANDARD_USER' "
            "WHERE role IN ('HOME_USER', 'SYSTEM')"
        )

    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "device_access",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("can_control", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "device_id"),
    )
    op.create_index(
        "ix_device_access_device_id",
        "device_access",
        ["device_id"],
        unique=False,
    )
    op.execute(
        sa.text(
            "INSERT INTO device_access (user_id, device_id, can_control) "
            "SELECT owner_user_id, id, true FROM devices "
            "WHERE owner_user_id IS NOT NULL"
        )
    )
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "registration_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO system_settings (id, registration_enabled) "
            "VALUES (1, true)"
        )
    )


def downgrade() -> None:
    op.drop_table("system_settings")
    op.drop_index("ix_device_access_device_id", table_name="device_access")
    op.drop_table("device_access")
    op.drop_column("users", "is_active")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "UPDATE users SET role = 'HOME_USER' WHERE role = 'STANDARD_USER'"
        )
        op.execute("ALTER TYPE user_role RENAME VALUE 'STANDARD_USER' TO 'HOME_USER'")
    else:
        op.execute("UPDATE users SET role = 'HOME_USER' WHERE role = 'STANDARD_USER'")
