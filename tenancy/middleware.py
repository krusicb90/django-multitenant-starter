"""
Selects the tenant database for each request from the signed-in user's
organization.
"""

from django.shortcuts import redirect
from django.urls import reverse

from .context import activate, deactivate


class TenantMiddleware:
    """
    For a signed-in member of an organization: activates that organization's
    database for the request and exposes it as request.organization.

    Requests without a usable tenant (anonymous users, platform superadmins,
    suspended or not yet provisioned organizations) run without a tenant
    context, in which any query on a tenant model raises instead of reaching
    the wrong database.
    """

    # Paths that work without a tenant.
    PUBLIC_PREFIXES = (
        "/accounts/",
        "/register/",
        "/registration-pending/",
        "/verify-email/",
        "/resend-verification/",
        "/invitation/",
        "/admin/",
        "/superadmin/",
        "/static/",
        "/health/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.organization = None
        user = request.user

        if not user.is_authenticated:
            return self.get_response(request)

        organization = user.organization
        is_public = request.path.startswith(self.PUBLIC_PREFIXES)

        if organization is None:
            if user.is_superuser or is_public:
                return self.get_response(request)
            return self._redirect_unless_there(request, "organization_setup")

        if not organization.is_active:
            if is_public:
                return self.get_response(request)
            return self._redirect_unless_there(request, "organization_suspended")

        if not organization.db_ready:
            request.organization = organization
            if is_public:
                return self.get_response(request)
            return self._redirect_unless_there(request, "organization_setup")

        request.organization = organization
        token = activate(organization)
        try:
            return self.get_response(request)
        finally:
            deactivate(token)

    def _redirect_unless_there(self, request, url_name):
        if request.path == reverse(url_name):
            return self.get_response(request)
        return redirect(url_name)
