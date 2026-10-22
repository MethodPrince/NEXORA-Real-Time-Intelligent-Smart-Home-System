import logging
from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class DatabaseNotConfiguredError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _get_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


@lru_cache(maxsize=4)
def _get_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(
        bind=_get_engine(database_url),
        autoflush=False,
        expire_on_commit=False,
    )


def get_engine() -> Engine:
    database_url = get_settings().database_url
    if not database_url:
        raise DatabaseNotConfiguredError("DATABASE_URL is not configured")
    return _get_engine(database_url)


def get_session() -> Generator[Session, None, None]:
    database_url = get_settings().database_url
    if not database_url:
        raise DatabaseNotConfiguredError("DATABASE_URL is not configured")

    session_factory = _get_session_factory(database_url)
    with session_factory() as session:
        yield session


def check_database_connection() -> str:
    database_url = get_settings().database_url
    if not database_url:
        return "not_configured"

    try:
        with _get_engine(database_url).connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Database health check failed")
        return "unavailable"
    return "connected"
