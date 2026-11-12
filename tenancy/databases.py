"""
Low-level database operations for tenants: registering a connection at
runtime, and creating, checking and dropping the PostgreSQL database.
"""

import copy
import re
from pathlib import Path

from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, connections

# PostgreSQL identifiers are limited to 63 bytes. Names are restricted to a
# safe subset so they can also be used as connection aliases and file names.
_DB_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class InvalidDatabaseName(ValueError):
    pass


def validate_db_name(name):
    if not isinstance(name, str) or not _DB_NAME_RE.match(name):
        raise InvalidDatabaseName(f"Invalid tenant database name: {name!r}")
    return name


def is_postgres(alias=DEFAULT_DB_ALIAS):
    return connections.settings[alias]["ENGINE"] == "django.db.backends.postgresql"


def ensure_database(alias):
    """
    Register a tenant database with Django if it is not registered yet.

    Tenant databases are not listed in settings.DATABASES. Each one is a copy
    of the default connection settings with a different database name, added
    under an alias equal to that name the first time a process needs it.
    """
    databases = connections.settings
    if alias in databases:
        return
    validate_db_name(alias)
    config = copy.deepcopy(databases[DEFAULT_DB_ALIAS])
    if is_postgres():
        config["NAME"] = alias
    else:
        # SQLite, for development without PostgreSQL: one file per tenant.
        config["NAME"] = str(Path(settings.BASE_DIR) / f"{alias}.sqlite3")
    databases[alias] = config


def forget_database(alias):
    """Close and unregister a tenant connection (after its database is dropped)."""
    if alias == DEFAULT_DB_ALIAS or alias not in connections.settings:
        return
    try:
        connections[alias].close()
        del connections[alias]
    finally:
        connections.settings.pop(alias, None)


def _maintenance_connection():
    """Autocommit connection used for CREATE DATABASE and DROP DATABASE."""
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    config = connections.settings[DEFAULT_DB_ALIAS]
    params = {
        "host": config.get("HOST") or None,
        "port": config.get("PORT") or None,
        "user": config.get("USER") or None,
        "password": config.get("PASSWORD") or None,
        "dbname": settings.DB_MAINTENANCE_NAME,
    }
    params.update(config.get("OPTIONS") or {})
    connection = psycopg2.connect(**{k: v for k, v in params.items() if v is not None})
    connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    return connection


def database_exists(name):
    validate_db_name(name)
    connection = _maintenance_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", [name])
            return cursor.fetchone() is not None
    finally:
        connection.close()


def create_database(name):
    """Create the database. Returns False when it already existed."""
    from psycopg2 import sql

    validate_db_name(name)
    connection = _maintenance_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", [name])
            if cursor.fetchone():
                return False
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            return True
    finally:
        connection.close()


def drop_database(name):
    """Drop the database. Returns False when it did not exist."""
    from psycopg2 import sql

    validate_db_name(name)
    if name in (settings.DB_MAINTENANCE_NAME, connections.settings[DEFAULT_DB_ALIAS]["NAME"]):
        raise InvalidDatabaseName(f"Refusing to drop {name!r}")
    connection = _maintenance_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", [name])
            if not cursor.fetchone():
                return False
            # Open connections would make DROP DATABASE fail.
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                [name],
            )
            cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
            return True
    finally:
        connection.close()
