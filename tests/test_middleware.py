from datetime import timedelta

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.utils import timezone

from accounts.models import User
from notes.models import Note
from organizations.models import Organization, Subscription
from tenancy.context import get_current_db
from tenancy.middleware import TenantMiddleware

from .conftest import TENANT_A


def test_anonymous_user_is_sent_to_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/")


def test_public_pages_work_without_a_tenant(client):
    assert client.get("/accounts/login/").status_code == 200
    assert client.get("/register/").status_code == 200
    assert client.get("/health/").json() == {"status": "ok"}


def test_member_gets_the_organization_on_the_request(client, org_a):
    client.force_login(org_a.owner)
    response = client.get("/")
    assert response.status_code == 200
    assert response.wsgi_request.organization == org_a


def test_suspended_organization_is_locked_out(client, org_a):
    org_a.status = Organization.Status.SUSPENDED
    org_a.save()
    client.force_login(org_a.owner)

    response = client.get("/")
    assert response.status_code == 302
    assert response.url == "/organization-suspended/"
    assert client.get("/organization-suspended/").status_code == 200
    assert client.post("/notes/create/", {"title": "x"}).url == "/organization-suspended/"
    assert Note.objects.using(TENANT_A).count() == 0


def test_organization_without_database_goes_to_setup(client, make_org):
    organization = make_org("Gamma", "tenant_not_created", ready=False)
    client.force_login(organization.owner)

    response = client.get("/")
    assert response.url == "/organization-setup/"
    assert client.get("/organization-setup/").status_code == 200


def test_user_without_organization_goes_to_setup(client, make_user):
    client.force_login(make_user("loner@example.com"))
    assert client.get("/").url == "/organization-setup/"
    assert client.get("/organization-setup/").status_code == 200


def test_superadmin_without_organization_goes_to_the_panel(client, superadmin):
    client.force_login(superadmin)
    assert client.get("/").url == "/superadmin/"


def test_context_is_cleared_when_the_view_raises(org_a):
    def failing_view(request):
        assert get_current_db() == TENANT_A
        raise RuntimeError("boom")

    request = RequestFactory().get("/")
    request.user = org_a.owner
    with pytest.raises(RuntimeError):
        TenantMiddleware(failing_view)(request)
    assert get_current_db() is None


def test_anonymous_request_has_no_tenant():
    def view(request):
        return get_current_db(), request.organization

    request = RequestFactory().get("/")
    request.user = AnonymousUser()
    assert TenantMiddleware(view)(request) == (None, None)


def test_expired_trial_makes_the_workspace_read_only(client, org_a):
    Note.objects.using(TENANT_A).create(title="kept")
    Subscription.objects.filter(organization=org_a).update(
        trial_end=timezone.now() - timedelta(days=1)
    )
    client.force_login(org_a.owner)

    page = client.get("/")
    assert page.status_code == 200
    assert "kept" in page.content.decode()
    assert page.wsgi_request.org_read_only is True

    response = client.post("/notes/create/", {"title": "blocked"})
    assert response.url == "/licence/"
    assert Note.objects.using(TENANT_A).count() == 1
    # Signing out must stay possible.
    assert client.post("/accounts/logout/").url == "/accounts/login/"


def test_valid_licence_allows_writes(client, org_a):
    client.force_login(org_a.owner)
    client.post("/notes/create/", {"title": "allowed"})
    assert Note.objects.using(TENANT_A).filter(title="allowed").exists()


def test_read_only_role_cannot_write(client, org_a, make_user):
    viewer = make_user("viewer@alpha.example", organization=org_a, role=User.Role.READONLY)
    client.force_login(viewer)

    assert client.get("/").status_code == 200
    response = client.post("/notes/create/", {"title": "nope"})
    assert response.url == "/"
    assert Note.objects.using(TENANT_A).count() == 0


def test_plan_item_limit_is_enforced(client, org_a, plans):
    plans["Trial"].item_limit = 1
    plans["Trial"].save()
    client.force_login(org_a.owner)

    client.post("/notes/create/", {"title": "first"})
    client.post("/notes/create/", {"title": "second"})
    assert Note.objects.using(TENANT_A).count() == 1
