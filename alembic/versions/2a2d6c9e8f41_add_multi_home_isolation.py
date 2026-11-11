"""add home memberships, home-scoped data, and security-event context

Revision ID: 2a2d6c9e8f41
Revises: 5c81d2a74e90
Create Date: 2026-11-11 13:20:00.000000
"""

from typing import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "2a2d6c9e8f41"
down_revision: Union[str, Sequence[str], None] = "5c81d2a74e90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_HOME_ID = "00000000-0000-4000-8000-000000000001"


def upgrade() -> None:
    bind = op.get_bind()
    home_role = sa.Enum(
        "ADMIN",
        "STANDARD_USER",
        "GUEST",
        name="home_role",
        native_enum=bind.dialect.name == "postgresql",
    )
    op.create_table(
        "homes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO homes (id, name, created_at) "
            "VALUES (:id, 'NEXORA Home', CURRENT_TIMESTAMP)"
        ).bindparams(id=LEGACY_HOME_ID)
    )
    op.create_table(
        "home_memberships",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("home_id", sa.Uuid(), nullable=False),
        sa.Column("role", home_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["home_id"], ["homes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "home_id"),
    )
    op.create_index(
        "ix_home_memberships_home_id",
        "home_memberships",
        ["home_id"],
        unique=False,
    )
    op.execute(
        sa.text(
            "INSERT INTO home_memberships (user_id, home_id, role, created_at) "
            "SELECT id, :home_id, "
            "CASE WHEN role = 'ADMIN' THEN 'ADMIN' "
            "WHEN role = 'GUEST' THEN 'GUEST' ELSE 'STANDARD_USER' END, "
            "CURRENT_TIMESTAMP FROM users"
        ).bindparams(home_id=LEGACY_HOME_ID)
    )

    for table in ("devices", "automation_rules", "activity_logs"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column("home_id", sa.Uuid(), nullable=True))
            batch_op.create_foreign_key(
                f"fk_{table}_home_id_homes",
                "homes",
                ["home_id"],
                ["id"],
                ondelete="CASCADE",
            )
        op.execute(
            sa.text(f"UPDATE {table} SET home_id = :home_id WHERE home_id IS NULL")
            .bindparams(home_id=LEGACY_HOME_ID)
        )
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                "home_id",
                existing_type=sa.Uuid(),
                nullable=False,
            )
        op.create_index(f"ix_{table}_home_id", table, ["home_id"], unique=False)

    with op.batch_alter_table("security_events") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_security_events_user_id_users",
            "users",
            ["user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_security_events_user_id",
        "security_events",
        ["user_id"],
        unique=False,
    )
    with op.batch_alter_table("security_events") as batch_op:
        batch_op.add_column(sa.Column("home_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_security_events_home_id_homes",
            "homes",
            ["home_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_security_events_home_id",
        "security_events",
        ["home_id"],
        unique=False,
    )
    op.add_column(
        "security_events",
        sa.Column("source_ip", sa.String(length=45), nullable=True),
    )
    op.add_column(
        "security_events",
        sa.Column(
            "outcome",
            sa.String(length=40),
            nullable=False,
            server_default="recorded",
        ),
    )
    op.add_column(
        "security_events",
        sa.Column(
            "metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "security_events",
        sa.Column("home_id_backfill", sa.Uuid(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE security_events SET home_id_backfill = :home_id "
            "WHERE home_id IS NULL"
        ).bindparams(home_id=LEGACY_HOME_ID)
    )
    op.execute("UPDATE security_events SET home_id = home_id_backfill")
    op.drop_column("security_events", "home_id_backfill")
    with op.batch_alter_table("security_events") as batch_op:
        batch_op.alter_column(
            "outcome",
            server_default=None,
            existing_type=sa.String(length=40),
        )
        batch_op.alter_column(
            "metadata",
            server_default=None,
            existing_type=sa.JSON(),
        )


def downgrade() -> None:
    op.drop_index("ix_security_events_home_id", table_name="security_events")
    op.drop_index("ix_security_events_user_id", table_name="security_events")
    with op.batch_alter_table("security_events") as batch_op:
        batch_op.drop_column("metadata")
        batch_op.drop_column("outcome")
        batch_op.drop_column("source_ip")
        batch_op.drop_column("home_id")
        batch_op.drop_column("user_id")

    for table in ("activity_logs", "automation_rules", "devices"):
        op.drop_index(f"ix_{table}_home_id", table_name=table)
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("home_id")

    op.drop_index("ix_home_memberships_home_id", table_name="home_memberships")
    op.drop_table("home_memberships")
    op.drop_table("homes")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        home_role = sa.Enum(name="home_role")
        home_role.drop(bind, checkfirst=True)
