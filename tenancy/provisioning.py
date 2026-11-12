"""
Tenant lifecycle: create the database, migrate it, seed it, and remove it.
"""

import logging
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.utils.module_loading import import_string

from .databases import (
    create_database,
    drop_database,
    ensure_database,
    forget_database,
    is_postgres,
    validate_db_name,
)

logger = logging.getLogger(__name__)


def migrate_tenant(alias, verbosity=0):
    """Apply the migrations of all tenant apps to one tenant database."""
    ensure_database(alias)
    # The router lets only TENANT_APPS migrate into a non-default database.
    call_command("migrate", database=alias, interactive=False, verbosity=verbosity)


def provision_tenant(organization):
    """
    Create and prepare the database of an organization.

    Safe to call again after a failure: an existing database is reused,
    migrations are idempotent, and seed hooks run only on the first success.
    """
    alias = validate_db_name(organization.db_name)
    if is_postgres():
        create_database(alias)
    migrate_tenant(alias)

    if not organization.db_ready:
        for dotted_path in settings.TENANT_SEED_HOOKS:
            import_string(dotted_path)(organization, alias)
        organization.db_ready = True
        organization.save(update_fields=["db_ready", "updated_at"])
    logger.info("Provisioned tenant database %s", alias)
    return alias


def deprovision_tenant(organization):
    """Drop the database of an organization. The organization row is left to the caller."""
    alias = validate_db_name(organization.db_name)
    if is_postgres():
        forget_database(alias)
        drop_database(alias)
    else:
        path = Path(connections.settings[alias]["NAME"]) if alias in connections.settings else None
        forget_database(alias)
        if path is not None and path.is_file():
            path.unlink()
    logger.info("Dropped tenant database %s", alias)


def migrate_all_tenants(stdout=None, verbosity=0):
    """Migrate every provisioned tenant database. Returns (migrated, failed) names."""
    from organizations.models import Organization

    migrated, failed = [], []
    for organization in Organization.objects.filter(db_ready=True).order_by("id"):
        try:
            migrate_tenant(organization.db_name, verbosity=verbosity)
            migrated.append(organization.db_name)
        except Exception as error:
            failed.append(organization.db_name)
            logger.exception("Migrating tenant %s failed", organization.db_name)
            if stdout is not None:
                stdout.write(f"  FAILED {organization.db_name}: {error}")
        finally:
            # A deploy touches every tenant; do not keep all connections open.
            connections[organization.db_name].close()
    return migrated, failed
