import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.emails import send_invitation_email, send_verification_email
from config.ratelimit import check_rate_limit
from config.turnstile import turnstile_passed, turnstile_site_key
from tenancy.provisioning import provision_tenant

from . import licensing
from .decorators import org_admin_required, tenant_required
from .forms import InvitationAcceptForm, InvitationForm, RegistrationForm
from .models import Invitation, Organization, Plan

logger = logging.getLogger(__name__)
User = get_user_model()

VERIFICATION_VALID_FOR = timedelta(hours=48)


def _try_provision(organization):
    """Provision the tenant database; on failure log it and leave db_ready False."""
    try:
        provision_tenant(organization)
    except Exception:
        logger.exception("Provisioning %s failed", organization.db_name)
        return False
    return True


# --- Signup -------------------------------------------------------------------


def register(request):
    """Create an organization and its owner account, on the trial plan."""
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = RegistrationForm(request.POST or None)
    status = 200
    if request.method == "POST":
        blocked, message = check_rate_limit(request, "register")
        if blocked:
            messages.error(request, message)
            status = 429
        elif not turnstile_passed(request):
            messages.error(request, "Verification failed. Please try again.")
            status = 400
        elif form.is_valid():
            return _create_organization(request, form.cleaned_data)

    context = {"form": form, "turnstile_site_key": turnstile_site_key(request)}
    return render(request, "organizations/register.html", context, status=status)


def _create_organization(request, data):
    trial_plan = Plan.objects.filter(is_trial=True).first()
    if trial_plan is None:
        licensing.seed_plans()
        trial_plan = Plan.objects.get(is_trial=True)

    skip_verification = settings.SKIP_EMAIL_VERIFICATION
    with transaction.atomic():
        user = User(
            username=data["email"],
            email=data["email"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            role=User.Role.ADMIN,
            is_org_owner=True,
            # The account stays inactive until the email address is confirmed.
            is_active=skip_verification,
            email_verified=skip_verification,
        )
        user.set_password(data["password1"])
        if not skip_verification:
            user.new_verification_token()
            user.email_verification_sent_at = timezone.now()
        user.save()

        organization = Organization.objects.create(
            name=data["organization_name"], owner=user, plan=trial_plan
        )
        user.organization = organization
        user.save(update_fields=["organization"])
        licensing.start_trial(organization)

    if skip_verification:
        _try_provision(organization)
        login(request, user)
        return redirect("dashboard")

    if not send_verification_email(user):
        messages.warning(
            request, "We could not send the verification email. Use the resend link below."
        )
    return redirect("registration_pending")


def registration_pending(request):
    return render(request, "organizations/registration_pending.html")


def verify_email(request, token):
    """
    Confirm an email address and create the tenant database.

    GET only shows a confirmation button. Mail scanners follow links in
    emails, and a token consumed on GET would be spent before the user
    clicked it.
    """
    user = (
        User.objects.filter(email_verification_token=token)
        .exclude(email_verification_token="")
        .first()
    )
    expired = (
        user is None
        or user.email_verification_sent_at is None
        or user.email_verification_sent_at < timezone.now() - VERIFICATION_VALID_FOR
    )
    if expired:
        return render(request, "organizations/verify_email.html", {"invalid": True}, status=400)

    if request.method != "POST":
        return render(request, "organizations/verify_email.html", {"email": user.email})

    user.email_verified = True
    user.is_active = True
    user.email_verification_token = ""
    user.save(update_fields=["email_verified", "is_active", "email_verification_token"])

    organization = user.organization
    if organization is not None and not organization.db_ready:
        # If this fails the user lands on the setup page, which can retry.
        _try_provision(organization)

    login(request, user)
    messages.success(request, "Your email address is confirmed.")
    return redirect("dashboard")


def resend_verification(request):
    if request.method == "POST":
        blocked, message = check_rate_limit(request, "resend")
        if blocked:
            messages.error(request, message)
        else:
            email = request.POST.get("email", "").strip().lower()
            user = User.objects.filter(username__iexact=email, email_verified=False).first()
            if user is not None:
                user.new_verification_token()
                user.email_verification_sent_at = timezone.now()
                user.save(update_fields=["email_verification_token", "email_verification_sent_at"])
                send_verification_email(user)
            # The same answer either way, so the form does not reveal who has an account.
            messages.success(
                request, "If that address is waiting for verification, a new email is on its way."
            )
        return redirect("registration_pending")
    return render(request, "organizations/resend_verification.html")


# --- Organization state -------------------------------------------------------


@login_required
def organization_setup(request):
    """Shown while the tenant database is missing; lets an admin retry provisioning."""
    organization = request.user.organization
    if organization is not None and organization.db_ready:
        return redirect("dashboard")

    if request.method == "POST" and organization is not None and request.user.is_org_admin:
        if _try_provision(organization):
            return redirect("dashboard")
        messages.error(request, "Setting up the workspace failed. Please try again later.")

    return render(request, "organizations/setup.html", {"pending_organization": organization})


@login_required
def organization_suspended(request):
    organization = request.user.organization
    if organization is None or organization.is_active:
        return redirect("dashboard")
    return render(request, "organizations/suspended.html", {"suspended_organization": organization})


@tenant_required
def licence_status(request):
    plans = Plan.objects.filter(is_active=True, is_trial=False)
    return render(request, "organizations/licence.html", {"plans": plans})


# --- Members and invitations --------------------------------------------------


@tenant_required
def members(request):
    organization = request.organization
    form = InvitationForm(organization=organization)
    context = {
        "members": organization.members.order_by("-is_active", "first_name", "last_name"),
        "invitations": organization.invitations.filter(accepted=False),
        "form": form,
        "can_add_user": organization.can_add_user(),
    }
    return render(request, "organizations/members.html", context)


@require_POST
@org_admin_required
def invite_member(request):
    organization = request.organization
    form = InvitationForm(request.POST, organization=organization)
    if not organization.can_add_user():
        messages.error(request, "Your plan's user limit is reached.")
    elif form.is_valid():
        invitation = Invitation.objects.create(
            organization=organization,
            email=form.cleaned_data["email"],
            role=form.cleaned_data["role"],
            invited_by=request.user,
        )
        if send_invitation_email(invitation):
            messages.success(request, f"Invitation sent to {invitation.email}.")
        else:
            messages.warning(request, "The invitation was created, but the email was not sent.")
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect("members")


@require_POST
@org_admin_required
def revoke_invitation(request, invitation_id):
    # Scoped to the current organization: an id from another tenant is a 404.
    invitation = get_object_or_404(
        Invitation, id=invitation_id, organization=request.organization, accepted=False
    )
    invitation.delete()
    messages.success(request, "Invitation revoked.")
    return redirect("members")


@require_POST
@org_admin_required
def deactivate_member(request, user_id):
    member = get_object_or_404(User, id=user_id, organization=request.organization)
    if member.is_org_owner or member == request.user:
        messages.error(request, "The owner and your own account cannot be deactivated.")
    else:
        member.is_active = False
        member.save(update_fields=["is_active"])
        messages.success(request, f"{member} was deactivated.")
    return redirect("members")


def invitation_accept(request, token):
    invitation = Invitation.objects.select_related("organization").filter(token=token).first()
    if invitation is None or not invitation.is_valid or not invitation.organization.is_active:
        return render(
            request, "organizations/invitation_accept.html", {"invalid": True}, status=400
        )

    if User.objects.filter(username__iexact=invitation.email).exists():
        return render(
            request, "organizations/invitation_accept.html", {"invalid": True}, status=400
        )

    form = InvitationAcceptForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = User(
                username=invitation.email,
                email=invitation.email,
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                organization=invitation.organization,
                role=invitation.role,
                email_verified=True,  # the invitation link proves ownership of the address
            )
            user.set_password(form.cleaned_data["password1"])
            user.save()
            invitation.accepted = True
            invitation.accepted_at = timezone.now()
            invitation.save(update_fields=["accepted", "accepted_at"])
        login(request, user)
        return redirect("dashboard")

    context = {"form": form, "invitation": invitation}
    return render(request, "organizations/invitation_accept.html", context)
