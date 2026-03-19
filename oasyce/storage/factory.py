"""Factory for creating ledger storage backends."""

from typing import Optional

from oasyce.storage.backend import LedgerBackend


def create_backend(
    backend_type: str = "sqlite",
    dsn: Optional[str] = None,
    db_path: str = "oasyce.db",
) -> LedgerBackend:
    """Create and initialize a storage backend.

    Args:
        backend_type: 'sqlite' (default) or 'postgres'.
        dsn: PostgreSQL connection string (required for postgres).
        db_path: SQLite database file path (used for sqlite).
    """
    if backend_type == "postgres":
        from oasyce.storage.postgres_backend import PostgresBackend

        if not dsn:
            raise ValueError("PostgreSQL requires a DSN (e.g. postgresql://user:pass@host/db)")
        backend = PostgresBackend(dsn)
    else:
        from oasyce.storage.sqlite_backend import SqliteBackend

        backend = SqliteBackend(db_path)
    backend.initialize()
    return backend
