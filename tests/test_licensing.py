from datetime import date, timedelta

import pytest
from django.utils import timezone

from organizations import licensing
from organizations.models import Plan, Subscription
from superadmin.models import AuditLog, GlobalSetting


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2025, 1, 15), 1, date(2025, 2, 15)),
        (date(2025, 1, 31), 1, date(2025, 2, 28)),
        (date(2024, 1, 31), 1, date(2024, 2, 29)),
        (date(2025, 11, 30), 3, date(2026, 2, 28)),
        (date(2024, 2, 29), 12, date(2025, 2, 28)),
    ],
)
def test_add_months_clamps_to_the_end_of_the_month(start, months, expected):
    assert licensing.add_months(start, months) == expected


def test_term_end_is_inclusive():
    assert licensing.term_end(date(2025, 3, 1), "monthly") == date(2025, 3, 31)
    assert licensing.term_end(date(2025, 3, 15), "yearly") == date(2026, 3, 14)


def test_new_organization_starts_on_a_valid_trial(org_a, settings):
    subscription = org_a.subscription
    assert subscription.status == Subscription.Status.TRIALING
    assert subscription.is_valid
    assert subscription.days_remaining == settings.TRIAL_PERIOD_DAYS - 1


def test_trial_past_its_end_is_not_valid(org_a):
    subscription = org_a.subscription
    subscription.trial_end = timezone.now() - timedelta(minutes=1)
    assert not subscription.is_valid


def test_activate_starts_a_term_and_changes_the_plan(org_a, plans, superadmin):
    today = timezone.localdate()
    subscription = licensing.activate(
        org_a, plan=plans["Team"], interval="yearly", actor=superadmin
    )

    org_a.refresh_from_db()
    assert org_a.plan == plans["Team"]
    assert subscription.status == Subscription.Status.ACTIVE
    assert subscription.active_since == today
    assert subscription.valid_until == licensing.term_end(today, "yearly")
    assert subscription.trial_end is None
    events = set(AuditLog.objects.filter(organization=org_a).values_list("event", flat=True))
    assert events == {"licence.plan", "licence.activate"}
    assert AuditLog.objects.filter(actor=superadmin).count() == 2


def test_extend_continues_from_the_end_of_a_running_term(org_a):
    today = timezone.localdate()
    licensing.activate(org_a, valid_until=today + timedelta(days=10))
    subscription = licensing.extend(org_a, months=1)
    assert subscription.valid_until == licensing.add_months(
        today + timedelta(days=11), 1
    ) - timedelta(days=1)


def test_extend_restarts_a_lapsed_licence_from_today(org_a):
    today = timezone.localdate()
    licensing.activate(org_a, valid_until=today - timedelta(days=90))
    Subscription.objects.filter(organization=org_a).update(status=Subscription.Status.EXPIRED)

    subscription = licensing.extend(org_a, months=1)
    assert subscription.status == Subscription.Status.ACTIVE
    assert subscription.valid_until == licensing.add_months(today, 1) - timedelta(days=1)


def test_extend_to_an_explicit_date(org_a):
    licensing.activate(org_a)
    target = timezone.localdate() + timedelta(days=500)
    assert licensing.extend(org_a, until=target).valid_until == target


def test_grace_period(org_a, settings):
    settings.LICENCE_GRACE_DAYS = 7
    today = timezone.localdate()

    subscription = licensing.activate(org_a, valid_until=today - timedelta(days=3))
    assert subscription.is_valid and subscription.in_grace
    assert subscription.days_remaining == -3

    subscription.valid_until = today - timedelta(days=8)
    assert not subscription.is_valid and not subscription.in_grace


def test_grace_days_can_be_changed_at_runtime(org_a):
    subscription = licensing.activate(org_a, valid_until=timezone.localdate() - timedelta(days=3))
    GlobalSetting.set("licence_grace_days", 1)
    assert not subscription.is_valid


def test_cancelled_licence_is_not_valid(org_a):
    licensing.activate(org_a)
    subscription = licensing.cancel(org_a)
    assert subscription.status == Subscription.Status.CANCELLED
    assert subscription.cancelled_at is not None
    assert not subscription.is_valid


def test_expire_overdue_respects_the_grace_period(org_a, org_b, settings):
    settings.LICENCE_GRACE_DAYS = 7
    today = timezone.localdate()
    licensing.activate(org_a, valid_until=today - timedelta(days=8))
    licensing.activate(org_b, valid_until=today - timedelta(days=7))

    assert licensing.expire_overdue() == [org_a]
    assert Subscription.objects.get(organization=org_a).status == "expired"
    assert Subscription.objects.get(organization=org_b).status == "active"


def test_expire_overdue_ends_finished_trials(org_a, org_b):
    Subscription.objects.filter(organization=org_a).update(
        trial_end=timezone.now() - timedelta(hours=1)
    )
    assert licensing.expire_overdue() == [org_a]
    assert Subscription.objects.get(organization=org_a).status == "expired"
    assert Subscription.objects.get(organization=org_b).status == "trialing"


def test_reminder_queries_match_the_exact_day(org_a, org_b):
    today = timezone.localdate()
    licensing.activate(org_a, valid_until=today + timedelta(days=7))
    Subscription.objects.filter(organization=org_b).update(
        trial_end=timezone.now() + timedelta(days=3)
    )

    assert [s.organization for s in licensing.licences_ending_in(7)] == [org_a]
    assert list(licensing.licences_ending_in(30)) == []
    assert [s.organization for s in licensing.trials_ending_in(3)] == [org_b]
    assert licensing.trials_ending_in(1) == []


def test_seed_plans_is_idempotent(db):
    assert licensing.seed_plans() == ["Trial", "Starter", "Team", "Business"]
    assert licensing.seed_plans() == []
    assert Plan.objects.filter(is_trial=True).count() == 1
