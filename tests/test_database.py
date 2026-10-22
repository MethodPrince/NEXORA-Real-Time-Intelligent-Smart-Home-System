from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy import inspect
from sqlalchemy import text

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
