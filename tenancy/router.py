"""
Database router.

Models of the apps listed in settings.TENANT_APPS live in the current tenant's
database. Everything else (users, organizations, plans, sessions, ...) lives
in the shared "default" database.
"""

from django.conf import settings
from django.db import DEFAULT_DB_ALIAS

from .context import get_current_db


class TenantContextMissing(RuntimeError):
    """A tenant model was queried while no tenant was active."""


def is_tenant_app(app_label):
    return app_label in settings.TENANT_APPS


class TenantDatabaseRouter:
    def _db_for(self, model):
        if not is_tenant_app(model._meta.app_label):
            return DEFAULT_DB_ALIAS
        alias = get_current_db()
        if alias is None:
            # Falling back to the shared database would silently mix tenants.
            raise TenantContextMissing(
                f"{model._meta.label} was queried outside a tenant context. "
                "Use tenancy.context.tenant_context(organization) or .using(alias)."
            )
        return alias

    def db_for_read(self, model, **hints):
        return self._db_for(model)

    def db_for_write(self, model, **hints):
        return self._db_for(model)

    def allow_relation(self, obj1, obj2, **hints):
        # Foreign keys cannot cross databases: shared models relate to shared
        # models, tenant models to tenant models.
        return is_tenant_app(obj1._meta.app_label) == is_tenant_app(obj2._meta.app_label)

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Shared apps migrate only into "default", tenant apps only into
        # tenant databases.
        if is_tenant_app(app_label):
            return db != DEFAULT_DB_ALIAS
        return db == DEFAULT_DB_ALIAS
