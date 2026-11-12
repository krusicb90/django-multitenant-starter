"""
Platform admin panel: organizations, licences, impersonation and IP blocks.
Only superusers get in.
"""

import ipaddress
from datetime import date
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from organizations import licensing
from organizations.models import Organization, Plan, Subscription
from tenancy.provisioning import deprovision_tenant

from .middleware import IMPERSONATED_SESSION_KEY
from .models import AuditLog, BlockedIP, RateLimitLog

User = get_user_model()


def superadmin_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        # While impersonating, request.user is the impersonated member.
        if request.impersonator is not None or not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


@superadmin_required
def dashboard(request):
    organizations = (
        Organization.objects.select_related("plan", "subscription", "owner")
        .annotate(member_count=Count("members", filter=Q(members__is_active=True)))
        .order_by("-created_at")
    )
    context = {
        "organizations": organizations,
        "recent_log": AuditLog.objects.select_related("organization", "actor")[:15],
    }
    return render(request, "superadmin/dashboard.html", context)


@superadmin_required
def organization_detail(request, org_id):
    organization = get_object_or_404(
        Organization.objects.select_related("plan", "owner"), id=org_id
    )
    context = {
        "org": organization,
        "org_subscription": getattr(organization, "subscription", None),
        "org_members": organization.members.order_by("-is_org_owner", "first_name"),
        "plans": Plan.objects.filter(is_active=True),
        "intervals": Subscription.Interval.choices,
        "log": organization.audit_logs.select_related("actor")[:30],
    }
    return render(request, "superadmin/organization_detail.html", context)


def _parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@require_POST
@superadmin_required
def organization_action(request, org_id):
    """Licence and status changes for one organization."""
    organization = get_object_or_404(Organization, id=org_id)
    action = request.POST.get("action")

    if action == "activate":
        plan = Plan.objects.filter(id=request.POST.get("plan") or None).first()
        licensing.activate(
            organization,
            plan=plan,
            interval=request.POST.get("interval"),
            valid_until=_parse_date(request.POST.get("valid_until")),
            actor=request.user,
        )
        messages.success(request, "Licence activated.")
    elif action == "extend":
        until = _parse_date(request.POST.get("until"))
        months = int(request.POST.get("months") or 0)
        if not hasattr(organization, "subscription") or not (until or months > 0):
            messages.error(request, "Give a number of months or a date.")
        else:
            licensing.extend(organization, months=months, until=until, actor=request.user)
            messages.success(request, "Licence extended.")
    elif action == "cancel":
        if hasattr(organization, "subscription"):
            licensing.cancel(organization, actor=request.user)
            messages.success(request, "Licence cancelled.")
    elif action == "set_plan":
        plan = get_object_or_404(Plan, id=request.POST.get("plan"))
        licensing.set_plan(organization, plan, actor=request.user)
        messages.success(request, "Plan changed.")
    elif action in ("suspend", "reactivate"):
        organization.status = (
            Organization.Status.SUSPENDED if action == "suspend" else Organization.Status.ACTIVE
        )
        organization.save(update_fields=["status", "updated_at"])
        AuditLog.log(f"organization.{action}", organization=organization, actor=request.user)
        messages.success(request, f"Organization {organization.get_status_display().lower()}.")
    else:
        messages.error(request, "Unknown action.")

    return redirect("superadmin_organization", org_id=organization.id)


@require_POST
@superadmin_required
def organization_delete(request, org_id):
    """Delete an organization, its users and its database. Requires typing the slug."""
    organization = get_object_or_404(Organization, id=org_id)
    if request.POST.get("confirm") != organization.slug:
        messages.error(request, "Type the organization's slug to confirm deletion.")
        return redirect("superadmin_organization", org_id=organization.id)

    name, db_name = organization.name, organization.db_name
    deprovision_tenant(organization)
    # The owner FK is PROTECT, so detach it before the members are cascaded away.
    organization.owner = None
    organization.save(update_fields=["owner"])
    organization.delete()
    AuditLog.log("organization.delete", f"{name} ({db_name})", actor=request.user)
    messages.success(request, f"{name} and its database were deleted.")
    return redirect("superadmin_dashboard")


@require_POST
@superadmin_required
def impersonate(request, user_id):
    target = get_object_or_404(User, id=user_id, is_superuser=False)
    request.session[IMPERSONATED_SESSION_KEY] = target.id
    AuditLog.log(
        "impersonation.start",
        f"as {target.username}",
        organization=target.organization,
        actor=request.user,
    )
    return redirect("dashboard")


@require_POST
def stop_impersonation(request):
    impersonator = getattr(request, "impersonator", None)
    if impersonator is None:
        raise PermissionDenied
    request.session.pop(IMPERSONATED_SESSION_KEY, None)
    AuditLog.log(
        "impersonation.stop",
        f"as {request.user.username}",
        organization=request.user.organization,
        actor=impersonator,
    )
    return redirect("superadmin_dashboard")


@superadmin_required
def blocked_ips(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "block":
            try:
                ip = str(ipaddress.ip_address(request.POST.get("ip", "").strip()))
            except ValueError:
                messages.error(request, "Not a valid IP address.")
            else:
                BlockedIP.objects.update_or_create(
                    ip=ip,
                    defaults={
                        "reason": request.POST.get("reason", "")[:255],
                        "blocked_by": request.user,
                        "is_active": True,
                    },
                )
                AuditLog.log("ip.block", ip, actor=request.user)
        elif action == "unblock":
            entry = get_object_or_404(BlockedIP, id=request.POST.get("id"))
            entry.is_active = False
            entry.save(update_fields=["is_active"])
            AuditLog.log("ip.unblock", entry.ip, actor=request.user)
        return redirect("superadmin_blocked_ips")

    context = {
        "blocked": BlockedIP.objects.filter(is_active=True),
        "rate_limit_log": RateLimitLog.objects.all()[:50],
    }
    return render(request, "superadmin/blocked_ips.html", context)
