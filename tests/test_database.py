from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy import inspect
from sqlalchemy import text
from uuid import uuid4

from app.core.config import Settings
from app.db import models
from app.db.base import Base
from app.db.session import check_database_connection
from app.db.session import get_engine


def test_models_import_and_define_expected_tables() -> None:
    assert {
        "users",
        "devices",
        "sensors",
        "automation_rules",
        "activity_logs",
        "security_events",
    } <= set(Base.metadata.tables)
    assert models.User.__tablename__ == "users"


def test_database_connection_uses_configured_sqlite_engine(monkeypatch, tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'health.db').as_posix()}"
    settings = Settings(DATABASE_URL=database_url)
    monkeypatch.setattr("app.db.session.get_settings", lambda: settings)

    with get_engine().connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
    assert check_database_connection() == "connected"


def test_initial_migration_creates_and_downgrades_all_tables(tmp_path) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    engine = create_engine(database_url)
    assert engine.dialect.name == "sqlite"

    expected_tables = {
        "users",
        "devices",
        "sensors",
        "automation_rules",
        "activity_logs",
        "security_events",
        "alembic_version",
    }

    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            assert expected_tables <= set(inspect(connection).get_table_names())

            command.downgrade(config, "base")
            assert "users" not in inspect(connection).get_table_names()
    finally:
        engine.dispose()


def test_multi_home_migration_preserves_existing_users_and_devices(tmp_path) -> None:
    database_path = tmp_path / "multi-home-backfill.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    engine = create_engine(database_url)
    user_id = str(uuid4())
    device_id = str(uuid4())

    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "c82f73b591ae")
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, name, email, password_hash, role, created_at, updated_at) "
                    "VALUES (:id, 'Existing User', 'existing@example.com', 'hash', "
                    "'HOME_USER', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": user_id},
            )
            connection.execute(
                text(
                    "INSERT INTO devices "
                    "(id, owner_user_id, name, device_type, status, online, created_at, updated_at) "
                    "VALUES (:id, :user_id, 'Existing light', 'smart_light', "
                    "'Off', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": device_id, "user_id": user_id},
            )
            connection.commit()
            command.upgrade(config, "head")

            home_id = connection.execute(
                text("SELECT home_id FROM home_memberships WHERE user_id = :user_id"),
                {"user_id": user_id},
            ).scalar_one()
            assert connection.execute(
                text("SELECT name FROM devices WHERE id = :device_id"),
                {"device_id": device_id},
            ).scalar_one() == "Existing light"
            assert connection.execute(
                text("SELECT home_id FROM devices WHERE id = :device_id"),
                {"device_id": device_id},
            ).scalar_one() == home_id
            assert connection.execute(
                text("SELECT can_control FROM device_access WHERE user_id = :user_id"),
                {"user_id": user_id},
            ).scalar_one() == 1
    finally:
        engine.dispose()
