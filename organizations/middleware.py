"""
Read-only mode: for organizations without a valid licence, and for users with
the read-only role.
"""

from django.contrib import messages
from django.shortcuts import redirect

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


class SubscriptionMiddleware:
    """
    Must run after TenantMiddleware. Sets request.org_read_only and
    request.user_read_only, and refuses state-changing requests while either
    is true. Data stays readable, so an expired customer can still export it.
    """

    # Writes that stay possible in read-only mode.
    ALWAYS_ALLOWED = ("/accounts/", "/licence/", "/superadmin/", "/admin/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.org_read_only = False
        request.user_read_only = False

        user = request.user
        organization = getattr(request, "organization", None)
        if not user.is_authenticated or organization is None or user.is_superuser:
            return self.get_response(request)

        # A platform admin impersonating a member is not locked out.
        impersonating = getattr(request, "impersonator", None) is not None

        subscription = getattr(organization, "subscription", None)
        if subscription is not None and not subscription.is_valid and not impersonating:
            request.org_read_only = True
            if self._is_blocked_write(request):
                messages.warning(
                    request,
                    "Your licence has expired. The workspace is read-only until it is renewed.",
                )
                return redirect("licence_status")

        if user.role == user.Role.READONLY:
            request.user_read_only = True
            if self._is_blocked_write(request):
                messages.warning(request, "Your role allows viewing only.")
                return redirect("dashboard")

        return self.get_response(request)

    def _is_blocked_write(self, request):
        return request.method not in SAFE_METHODS and not request.path.startswith(
            self.ALWAYS_ALLOWED
        )
