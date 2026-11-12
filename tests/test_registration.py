from datetime import timedelta

from django.core import mail
from django.db import connections
from django.utils import timezone

from accounts.models import User
from notes.models import Note
from organizations.models import Organization, Subscription
from superadmin.models import RateLimitLog

from .conftest import PASSWORD

FORM = {
    "organization_name": "Acme Ltd",
    "first_name": "Ada",
    "last_name": "Lovelace",
    "email": "ada@acme.example",
    "password1": PASSWORD,
    "password2": PASSWORD,
}


def verification_path(user):
    return f"/verify-email/{user.email_verification_token}/"


def test_registration_creates_an_inactive_owner_and_a_trial(client, plans):
    response = client.post("/register/", FORM)
    assert response.url == "/registration-pending/"

    user = User.objects.get(username="ada@acme.example")
    organization = user.organization
    assert not user.is_active and not user.email_verified
    assert user.is_org_owner and user.is_org_admin
    assert organization.owner == user
    assert organization.plan == plans["Trial"]
    assert organization.db_name.startswith("tenant_acme_ltd_")
    assert organization.subscription.status == Subscription.Status.TRIALING
    # No database until the address is confirmed.
    assert not organization.db_ready
    assert organization.db_name not in connections.settings

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["ada@acme.example"]
    assert verification_path(user) in mail.outbox[0].body


def test_unverified_user_cannot_sign_in(client, plans):
    client.post("/register/", FORM)
    response = client.post(
        "/accounts/login/", {"username": "ada@acme.example", "password": PASSWORD}
    )
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


def test_opening_the_link_does_not_consume_the_token(client, plans):
    client.post("/register/", FORM)
    user = User.objects.get(username="ada@acme.example")

    assert client.get(verification_path(user)).status_code == 200
    user.refresh_from_db()
    assert not user.is_active and user.email_verification_token


def test_confirming_creates_the_tenant_database(client, plans, provisioning_sandbox):
    client.post("/register/", FORM)
    user = User.objects.get(username="ada@acme.example")

    response = client.post(verification_path(user))
    assert response.url == "/"

    user.refresh_from_db()
    organization = Organization.objects.get(owner=user)
    assert user.is_active and user.email_verified and user.email_verification_token == ""
    assert organization.db_ready
    assert "notes_note" in connections[organization.db_name].introspection.table_names()
    # The seed hook ran in the new database.
    assert Note.objects.using(organization.db_name).count() == 1

    page = client.get("/")
    assert page.status_code == 200
    assert "Welcome to Acme Ltd" in page.content.decode()


def test_used_or_unknown_token_is_rejected(client, plans, provisioning_sandbox):
    client.post("/register/", FORM)
    path = verification_path(User.objects.get(username="ada@acme.example"))
    client.post(path)
    client.post("/accounts/logout/")

    assert client.get(path).status_code == 400
    assert client.post("/verify-email/not-a-token/").status_code == 400


def test_expired_token_is_rejected(client, plans):
    client.post("/register/", FORM)
    user = User.objects.get(username="ada@acme.example")
    User.objects.filter(id=user.id).update(
        email_verification_sent_at=timezone.now() - timedelta(hours=49)
    )

    assert client.post(verification_path(user)).status_code == 400
    user.refresh_from_db()
    assert not user.is_active


def test_resend_issues_a_new_token_without_revealing_accounts(client, plans):
    client.post("/register/", FORM)
    old_token = User.objects.get(username="ada@acme.example").email_verification_token
    mail.outbox.clear()

    known = client.post("/resend-verification/", {"email": "ada@acme.example"}, follow=True)
    unknown = client.post("/resend-verification/", {"email": "nobody@acme.example"}, follow=True)

    assert User.objects.get(username="ada@acme.example").email_verification_token != old_token
    assert len(mail.outbox) == 1
    notice = "If that address is waiting for verification"
    assert notice in known.content.decode() and notice in unknown.content.decode()


def test_duplicate_email_is_refused(client, plans):
    client.post("/register/", FORM)
    response = client.post("/register/", {**FORM, "email": "ADA@acme.example"})
    assert response.status_code == 200
    assert "already exists" in response.content.decode()
    assert Organization.objects.count() == 1


def test_weak_or_mismatched_password_is_refused(client, plans):
    assert (
        client.post("/register/", {**FORM, "password1": "12345", "password2": "12345"}).status_code
        == 200
    )
    assert client.post("/register/", {**FORM, "password2": "different"}).status_code == 200
    assert User.objects.count() == 0


def test_skip_verification_signs_in_and_provisions_immediately(
    client, plans, settings, provisioning_sandbox
):
    settings.SKIP_EMAIL_VERIFICATION = True
    response = client.post("/register/", FORM)

    assert response.url == "/"
    organization = Organization.objects.get()
    assert organization.db_ready
    assert len(mail.outbox) == 0
    assert client.get("/").status_code == 200


def test_failed_provisioning_can_be_retried(client, plans, provisioning_sandbox, monkeypatch):
    from organizations import views

    def broken(organization):
        raise RuntimeError("database server unavailable")

    client.post("/register/", FORM)
    user = User.objects.get(username="ada@acme.example")
    real_provision = views.provision_tenant
    monkeypatch.setattr(views, "provision_tenant", broken)

    client.post(verification_path(user))
    assert not Organization.objects.get().db_ready
    assert client.get("/").url == "/organization-setup/"
    assert client.post("/organization-setup/").status_code == 200

    monkeypatch.setattr(views, "provision_tenant", real_provision)
    assert client.post("/organization-setup/").url == "/"
    assert Organization.objects.get().db_ready
    assert client.get("/").status_code == 200


def test_registration_is_rate_limited(client, plans, settings):
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "register": (2, 3600)}
    bad = {**FORM, "password2": "different"}

    assert client.post("/register/", bad).status_code == 200
    assert client.post("/register/", bad).status_code == 200
    assert client.post("/register/", FORM).status_code == 429
    assert Organization.objects.count() == 0
    assert RateLimitLog.objects.filter(endpoint="register").count() == 1
