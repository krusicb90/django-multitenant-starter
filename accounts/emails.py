"""Transactional emails. Every function returns True when the message was sent."""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger(__name__)


def absolute_url(name, *args):
    return f"{settings.SITE_URL}{reverse(name, args=args)}"


def send_templated(to, subject, template, context):
    if not settings.EMAIL_ENABLED:
        logger.info("Email disabled, not sending %r to %s", subject, to)
        return False
    body = render_to_string(template, {"site_name": settings.SITE_NAME, **context})
    try:
        send_mail(f"[{settings.SITE_NAME}] {subject}", body, settings.DEFAULT_FROM_EMAIL, [to])
    except Exception:
        logger.exception("Sending %r to %s failed", subject, to)
        return False
    return True


def send_verification_email(user):
    return send_templated(
        user.email,
        "Confirm your email address",
        "emails/verify_email.txt",
        {"user": user, "url": absolute_url("verify_email", user.email_verification_token)},
    )


def send_invitation_email(invitation):
    return send_templated(
        invitation.email,
        f"Invitation to join {invitation.organization.name}",
        "emails/invitation.txt",
        {"invitation": invitation, "url": absolute_url("invitation_accept", invitation.token)},
    )


def send_licence_reminder(organization, kind, days_left):
    """kind is "trial" or "licence". Sent to the organization's owner."""
    owner = organization.owner
    if owner is None or not owner.email:
        return False
    subject = (
        f"Your trial ends in {days_left} day(s)"
        if kind == "trial"
        else f"Your licence expires in {days_left} day(s)"
    )
    return send_templated(
        owner.email,
        subject,
        "emails/licence_reminder.txt",
        {
            "organization": organization,
            "kind": kind,
            "days_left": days_left,
            "url": absolute_url("licence_status"),
        },
    )
