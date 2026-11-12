"""
Licence rules: trial, activation, extension, cancellation and expiry.

Every change is written to the superadmin audit log.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from .models import Plan, Subscription


def add_months(day, months):
    """The same day of the month N months later, clamped to the end of that month."""
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def term_end(start, interval):
    """Last day (inclusive) of a licence term starting on `start`."""
    months = 12 if interval == Subscription.Interval.YEARLY else 1
    return add_months(start, months) - timedelta(days=1)


def _log(event, message, organization, actor=None):
    from superadmin.models import AuditLog

    AuditLog.log(event, message, organization=organization, actor=actor)


def _current(organization):
    """
    The subscription as stored now. organization.subscription may hold a stale
    cached instance, and saving that would overwrite newer values.
    """
    subscription = Subscription.objects.get(organization=organization)
    organization.subscription = subscription
    return subscription


def start_trial(organization):
    """Create the trial subscription of a new organization."""
    return Subscription.objects.create(
        organization=organization,
        status=Subscription.Status.TRIALING,
        trial_end=timezone.now() + timedelta(days=settings.TRIAL_PERIOD_DAYS),
    )


def set_plan(organization, plan, actor=None):
    old = organization.plan.name if organization.plan else "-"
    organization.plan = plan
    organization.save(update_fields=["plan", "updated_at"])
    _log("licence.plan", f"{old} -> {plan.name if plan else '-'}", organization, actor)


def activate(organization, plan=None, interval=None, start=None, valid_until=None, actor=None):
    """
    Turn a trial or an expired licence into an active one.

    Without an explicit valid_until the first term runs one month or one year
    from `start`, depending on the interval.
    """
    Subscription.objects.get_or_create(organization=organization)
    subscription = _current(organization)
    start = start or timezone.localdate()
    if plan is not None and organization.plan_id != plan.id:
        set_plan(organization, plan, actor=actor)
    if interval in Subscription.Interval.values:
        subscription.interval = interval
    subscription.status = Subscription.Status.ACTIVE
    subscription.active_since = start
    subscription.valid_until = valid_until or term_end(start, subscription.interval)
    subscription.trial_end = None
    subscription.cancelled_at = None
    subscription.save()
    _log(
        "licence.activate",
        f"{subscription.interval} until {subscription.valid_until:%Y-%m-%d}",
        organization,
        actor,
    )
    return subscription


def extend(organization, months=0, until=None, actor=None):
    """
    Extend a licence by N months, or to an explicit date.

    A term that is still running is extended from its end; a lapsed one from
    today, so that the customer does not pay for the gap.
    """
    subscription = _current(organization)
    today = timezone.localdate()
    old = subscription.valid_until
    base = old if old and old >= today else today - timedelta(days=1)
    if until is None:
        until = add_months(base + timedelta(days=1), months) - timedelta(days=1)
    subscription.valid_until = until
    if subscription.status != Subscription.Status.ACTIVE:
        subscription.status = Subscription.Status.ACTIVE
        subscription.trial_end = None
        subscription.cancelled_at = None
        subscription.active_since = subscription.active_since or today
    subscription.save()
    _log(
        "licence.extend",
        f"{old:%Y-%m-%d} -> {until:%Y-%m-%d}" if old else f"-> {until:%Y-%m-%d}",
        organization,
        actor,
    )
    return subscription


def cancel(organization, actor=None):
    subscription = _current(organization)
    old = subscription.status
    subscription.status = Subscription.Status.CANCELLED
    subscription.cancelled_at = timezone.now()
    subscription.save()
    _log("licence.cancel", f"{old} -> cancelled", organization, actor)
    return subscription


def expire_overdue():
    """
    Mark as expired: active licences past their grace period and trials past
    their end. Returns the affected organizations.
    """
    grace = Subscription.grace_days()
    cutoff = timezone.localdate() - timedelta(days=grace)
    expired = []

    overdue = Subscription.objects.filter(
        status=Subscription.Status.ACTIVE, valid_until__lt=cutoff
    ).select_related("organization")
    for subscription in overdue:
        subscription.status = Subscription.Status.EXPIRED
        subscription.save(update_fields=["status", "updated_at"])
        _log(
            "licence.expired",
            f"term ended {subscription.valid_until:%Y-%m-%d}, grace {grace} days",
            subscription.organization,
        )
        expired.append(subscription.organization)

    ended_trials = Subscription.objects.filter(
        status=Subscription.Status.TRIALING, trial_end__lt=timezone.now()
    ).select_related("organization")
    for subscription in ended_trials:
        subscription.status = Subscription.Status.EXPIRED
        subscription.save(update_fields=["status", "updated_at"])
        _log(
            "licence.trial_expired",
            f"trial ended {subscription.trial_end:%Y-%m-%d}",
            subscription.organization,
        )
        expired.append(subscription.organization)

    return expired


def licences_ending_in(days):
    """Active licences whose term ends exactly `days` days from today."""
    target = timezone.localdate() + timedelta(days=days)
    return Subscription.objects.filter(
        status=Subscription.Status.ACTIVE, valid_until=target
    ).select_related("organization", "organization__owner")


def trials_ending_in(days):
    """Trials that end on the calendar day `days` days from today."""
    target = timezone.localdate() + timedelta(days=days)
    return [
        subscription
        for subscription in Subscription.objects.filter(
            status=Subscription.Status.TRIALING, trial_end__isnull=False
        ).select_related("organization", "organization__owner")
        if timezone.localtime(subscription.trial_end).date() == target
    ]


# Example tiers: (name, user limit, item limit, monthly price). Yearly = 10 x monthly.
DEFAULT_TIERS = [
    ("Starter", 3, 100, Decimal("10.00")),
    ("Team", 15, 2000, Decimal("30.00")),
    ("Business", 0, 0, Decimal("90.00")),
]


def seed_plans():
    """Create the trial plan and the example tiers. Existing plans are left alone."""
    created = []
    if not Plan.objects.filter(is_trial=True).exists():
        Plan.objects.create(name="Trial", is_trial=True, order=0)
        created.append("Trial")
    for order, (name, users, items, monthly) in enumerate(DEFAULT_TIERS, start=1):
        if Plan.objects.filter(name=name).exists():
            continue
        Plan.objects.create(
            name=name,
            user_limit=users,
            item_limit=items,
            price_monthly=monthly,
            price_yearly=monthly * 10,
            order=order,
        )
        created.append(name)
    return created
