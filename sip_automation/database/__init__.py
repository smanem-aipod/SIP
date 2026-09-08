"""
PostgreSQL data-access package.

This package contains database connection management, schema inspection,
and repositories for raw, canonical, and reference datasets.
"""

from sip_automation.database.engine import (
    database_connection,
    database_transaction,
    get_database_engine,
)

__all__ = [
    "get_database_engine",
    "database_connection",
    "database_transaction",
]