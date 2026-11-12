from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def tenant_required(view):
    """The user must be signed in and inside a provisioned organization."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.organization is None or not request.organization.db_ready:
            if request.user.is_superuser:
                return redirect("superadmin_dashboard")
            return redirect("organization_setup")
        return view(request, *args, **kwargs)

    return wrapper


def org_admin_required(view):
    """Like tenant_required, and the user must be an admin of the organization."""

    @wraps(view)
    @tenant_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_org_admin:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper
