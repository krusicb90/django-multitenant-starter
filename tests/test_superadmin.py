from django.db import connections
from django.utils import timezone

from notes.models import Note
from organizations import licensing
from organizations.models import Organization, Subscription
from superadmin.middleware import IMPERSONATED_SESSION_KEY
from superadmin.models import AuditLog, BlockedIP
from tenancy.provisioning import provision_tenant

from .conftest import TENANT_A, TENANT_B


def test_panel_is_for_superusers_only(client, org_a, superadmin):
    assert client.get("/superadmin/").url.startswith("/accounts/login/")

    client.force_login(org_a.owner)
    assert client.get("/superadmin/").status_code == 403
    assert (
        client.post(
            f"/superadmin/organizations/{org_a.id}/action/", {"action": "suspend"}
        ).status_code
        == 403
    )
    client.post("/accounts/logout/")

    client.force_login(superadmin)
    page = client.get("/superadmin/")
    assert page.status_code == 200
    assert "Alpha" in page.content.decode()
    assert client.get(f"/superadmin/organizations/{org_a.id}/").status_code == 200


def test_activate_and_extend_from_the_panel(client, org_a, plans, superadmin):
    client.force_login(superadmin)
    action = f"/superadmin/organizations/{org_a.id}/action/"

    client.post(action, {"action": "activate", "plan": plans["Team"].id, "interval": "monthly"})
    subscription = Subscription.objects.get(organization=org_a)
    first_end = licensing.term_end(timezone.localdate(), "monthly")
    assert subscription.status == "active" and subscription.valid_until == first_end
    assert Organization.objects.get(id=org_a.id).plan == plans["Team"]

    client.post(action, {"action": "extend", "months": "2"})
    assert Subscription.objects.get(organization=org_a).valid_until > first_end

    client.post(action, {"action": "extend"})  # neither months nor date: ignored
    client.post(action, {"action": "cancel"})
    assert Subscription.objects.get(organization=org_a).status == "cancelled"
    assert AuditLog.objects.filter(organization=org_a, actor=superadmin).count() == 4


def test_suspend_and_reactivate(client, org_a, superadmin):
    client.force_login(superadmin)
    action = f"/superadmin/organizations/{org_a.id}/action/"

    client.post(action, {"action": "suspend"})
    assert not Organization.objects.get(id=org_a.id).is_active
    client.post(action, {"action": "reactivate"})
    assert Organization.objects.get(id=org_a.id).is_active


def test_impersonation_enters_the_members_tenant(client, org_a, org_b, superadmin):
    Note.objects.using(TENANT_A).create(title="Alpha note")
    Note.objects.using(TENANT_B).create(title="Beta note")
    client.force_login(superadmin)

    assert client.post(f"/superadmin/impersonate/{org_a.owner.id}/").url == "/"
    page = client.get("/")
    body = page.content.decode()
    assert page.wsgi_request.user == org_a.owner
    assert page.wsgi_request.impersonator == superadmin
    assert "Alpha note" in body and "Beta note" not in body
    # The panel is closed while acting as a member.
    assert client.get("/superadmin/").status_code == 403

    assert client.post("/superadmin/stop-impersonation/").url == "/superadmin/"
    assert client.get("/superadmin/").status_code == 200
    events = list(AuditLog.objects.order_by("id").values_list("event", flat=True))
    assert events == ["impersonation.start", "impersonation.stop"]
    assert AuditLog.objects.filter(actor=superadmin, organization=org_a).count() == 2


def test_impersonated_admin_can_write_in_an_expired_workspace(client, org_a, superadmin):
    Subscription.objects.filter(organization=org_a).update(status="expired")
    client.force_login(superadmin)
    client.post(f"/superadmin/impersonate/{org_a.owner.id}/")

    client.post("/notes/create/", {"title": "support fix"})
    assert Note.objects.using(TENANT_A).filter(title="support fix").exists()


def test_session_key_is_ignored_for_ordinary_users(client, org_a, org_b):
    client.force_login(org_a.owner)
    session = client.session
    session[IMPERSONATED_SESSION_KEY] = org_b.owner.id
    session.save()

    page = client.get("/")
    assert page.wsgi_request.user == org_a.owner
    assert page.wsgi_request.organization == org_a
    assert IMPERSONATED_SESSION_KEY not in client.session
    assert client.post("/superadmin/stop-impersonation/").status_code == 403


def test_superusers_cannot_be_impersonated(client, superadmin, make_user):
    other = make_user("second-root@platform.example", is_superuser=True)
    client.force_login(superadmin)
    assert client.post(f"/superadmin/impersonate/{other.id}/").status_code == 404


def test_delete_needs_the_slug_and_removes_the_database(
    client, plans, make_org, superadmin, provisioning_sandbox
):
    organization = make_org("Doomed", "tenant_doomed_0a1b2c3d", ready=False)
    provision_tenant(organization)
    assert "notes_note" in connections[organization.db_name].introspection.table_names()
    client.force_login(superadmin)
    delete = f"/superadmin/organizations/{organization.id}/delete/"

    client.post(delete, {"confirm": "wrong"})
    assert Organization.objects.filter(id=organization.id).exists()

    assert client.post(delete, {"confirm": organization.slug}).url == "/superadmin/"
    assert not Organization.objects.filter(id=organization.id).exists()
    assert "tenant_doomed_0a1b2c3d" not in connections.settings
    assert AuditLog.objects.filter(event="organization.delete").count() == 1


def test_blocking_an_ip_from_the_panel(client, superadmin):
    client.force_login(superadmin)

    client.post("/superadmin/blocked-ips/", {"action": "block", "ip": "not-an-ip"})
    assert BlockedIP.objects.count() == 0

    client.post(
        "/superadmin/blocked-ips/", {"action": "block", "ip": "203.0.113.77", "reason": "scanner"}
    )
    entry = BlockedIP.objects.get()
    assert entry.blocked_by == superadmin
    assert client.get("/health/", REMOTE_ADDR="203.0.113.77").status_code == 403

    client.post("/superadmin/blocked-ips/", {"action": "unblock", "id": entry.id})
    assert client.get("/health/", REMOTE_ADDR="203.0.113.77").status_code == 200


def test_django_admin_shows_shared_models_only(client, superadmin, org_a):
    client.force_login(superadmin)
    page = client.get("/admin/")
    assert page.status_code == 200
    body = page.content.decode()
    assert "/admin/organizations/organization/" in body
    assert "/admin/notes/" not in body
    assert client.get("/admin/organizations/organization/").status_code == 200
