"""
The current tenant.

The active organization is kept in a ContextVar, which is isolated per thread
under WSGI and per task under ASGI. TenantMiddleware sets it for the duration
of a request; background code uses the tenant_context() context manager.
"""

from contextvars import ContextVar

from .databases import ensure_database

_current_tenant = ContextVar("current_tenant", default=None)


def get_current_tenant():
    """The active organization, or None outside a tenant context."""
    return _current_tenant.get()


def get_current_db():
    """Database alias of the active tenant, or None outside a tenant context."""
    tenant = _current_tenant.get()
    return tenant.db_name if tenant is not None else None


def activate(organization):
    """Make `organization` the current tenant. Returns a token for deactivate()."""
    ensure_database(organization.db_name)
    return _current_tenant.set(organization)


def deactivate(token=None):
    """Restore the tenant that was active before the matching activate() call."""
    if token is not None:
        _current_tenant.reset(token)
    else:
        _current_tenant.set(None)


class tenant_context:
    """
    Run a block of code against one organization's database.

        with tenant_context(organization):
            Note.objects.count()
    """

    def __init__(self, organization):
        self.organization = organization
        self._token = None

    def __enter__(self):
        self._token = activate(self.organization)
        return self.organization

    def __exit__(self, exc_type, exc, traceback):
        deactivate(self._token)
        return False
