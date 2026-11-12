from datetime import timedelta
from io import StringIO

import pytest
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from accounts.models import User
from organizations import licensing
from organizations.models import Plan, Subscription
from tenancy import provisioning


def run(name, *args):
    out = StringIO()
    call_command(name, *args, stdout=out)
    return out.getvalue()


def test_seed_plans(db):
    assert "Trial, Starter, Team, Business" in run("seed_plans")
    assert "none" in run("seed_plans")
    assert Plan.objects.count() == 4


def test_expire_licences(org_a, org_b):
    Subscription.objects.filter(organization=org_a).update(
        trial_end=timezone.now() - timedelta(days=1)
    )
    assert "Expired 1" in run("expire_licences")
    assert Subscription.objects.get(organization=org_a).status == "expired"


def test_licence_reminders_go_to_the_owner_on_the_configured_days(org_a, org_b, settings):
    settings.TRIAL_REMINDER_DAYS = [3]
    settings.LICENCE_REMINDER_DAYS = [7]
    Subscription.objects.filter(organization=org_a).update(
        trial_end=timezone.now() + timedelta(days=3)
    )
    licensing.activate(org_b, valid_until=timezone.localdate() + timedelta(days=7))

    assert "Sent 2" in run("send_licence_reminders")
    by_recipient = {message.to[0]: message for message in mail.outbox}
    assert "trial ends in 3 day" in by_recipient[org_a.owner.email].subject
    assert "licence expires in 7 day" in by_recipient[org_b.owner.email].subject

    mail.outbox.clear()
    settings.TRIAL_REMINDER_DAYS = [1]
    settings.LICENCE_REMINDER_DAYS = [1]
    assert "Sent 0" in run("send_licence_reminders")


def test_ensure_superuser(db, monkeypatch):
    assert "skipping" in run("ensure_superuser")
    monkeypatch.setenv("SUPERUSER_USERNAME", "root")
    monkeypatch.setenv("SUPERUSER_EMAIL", "root@platform.example")
    monkeypatch.setenv("SUPERUSER_PASSWORD", "a-long-passphrase")

    assert "Created" in run("ensure_superuser")
    assert "already exists" in run("ensure_superuser")
    user = User.objects.get(username="root")
    assert user.is_superuser and user.organization is None


def test_migrate_tenants_covers_provisioned_organizations_only(org_a, org_b, make_org, monkeypatch):
    make_org("Pending", "tenant_pending", ready=False)
    seen = []
    monkeypatch.setattr(
        provisioning, "migrate_tenant", lambda alias, verbosity=0: seen.append(alias)
    )

    assert "Migrated 2" in run("migrate_tenants")
    assert seen == [org_a.db_name, org_b.db_name]


def test_migrate_tenants_fails_loudly_and_continues(org_a, org_b, monkeypatch):
    seen = []

    def migrate(alias, verbosity=0):
        seen.append(alias)
        if alias == org_a.db_name:
            raise RuntimeError("cannot connect")

    monkeypatch.setattr(provisioning, "migrate_tenant", migrate)
    with pytest.raises(CommandError, match=org_a.db_name):
        run("migrate_tenants")
    assert seen == [org_a.db_name, org_b.db_name]


def test_setup_tenant_needs_an_existing_organization(db):
    with pytest.raises(CommandError):
        run("setup_tenant", "missing")
