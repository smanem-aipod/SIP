from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from sip_automation.core.exceptions import RepositoryError
from sip_automation.core.logging import get_logger
from sip_automation.core.settings import get_settings


logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_database_engine() -> Engine:
    """
    Create and cache the PostgreSQL SQLAlchemy engine.

    The engine owns the connection pool. It should be reused throughout
    the application rather than recreated for every operation.
    """

    settings = get_settings()

    engine = create_engine(
        settings.postgres_url,
        pool_pre_ping=True,
        pool_size=settings.postgres_pool_size,
        max_overflow=settings.postgres_max_overflow,
        pool_timeout=settings.postgres_pool_timeout_seconds,
        pool_recycle=settings.postgres_pool_recycle_seconds,
        future=True,
    )

    logger.info(
        "database_engine_created",
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_database,
        pool_size=settings.postgres_pool_size,
        max_overflow=settings.postgres_max_overflow,
    )

    return engine


@contextmanager
def database_connection() -> Generator[Connection, None, None]:
    """
    Provide a database connection without automatically starting a write
    transaction.

    Appropriate for read operations.
    """

    engine = get_database_engine()

    try:
        with engine.connect() as connection:
            yield connection

    except SQLAlchemyError as exc:
        logger.exception(
            "database_connection_failed",
            error_type=type(exc).__name__,
        )

        raise RepositoryError(
            "Unable to open or use the PostgreSQL connection."
        ) from exc


@contextmanager
def database_transaction() -> Generator[Connection, None, None]:
    """
    Provide a transactional connection.

    The transaction is committed when the context completes successfully.
    It is rolled back automatically when an exception occurs.
    """

    engine = get_database_engine()

    try:
        with engine.begin() as connection:
            yield connection

    except SQLAlchemyError as exc:
        logger.exception(
            "database_transaction_failed",
            error_type=type(exc).__name__,
        )

        raise RepositoryError(
            "PostgreSQL transaction failed and was rolled back."
        ) from exc


def check_database_connection() -> bool:
    """
    Confirm that PostgreSQL is reachable.

    This does not inspect or modify any table.
    """

    try:
        with database_connection() as connection:
            connection.execute(text("SELECT 1"))

        logger.info("database_connection_check_succeeded")
        return True

    except RepositoryError:
        logger.exception("database_connection_check_failed")
        return False


def dispose_database_engine() -> None:
    """
    Dispose of the connection pool.

    Mainly useful during tests or controlled application shutdown.
    """

    get_database_engine().dispose()
    get_database_engine.cache_clear()

    logger.info("database_engine_disposed")