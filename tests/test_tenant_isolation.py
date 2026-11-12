from django.db import connections

from notes.models import Note
from tenancy.context import get_current_db, tenant_context

from .conftest import TENANT_A, TENANT_B


def test_rows_are_stored_per_tenant(org_a, org_b):
    with tenant_context(org_a):
        Note.objects.create(title="only in A")
    with tenant_context(org_b):
        Note.objects.create(title="only in B")
        Note.objects.create(title="second in B")

    with tenant_context(org_a):
        assert list(Note.objects.values_list("title", flat=True)) == ["only in A"]
    assert Note.objects.using(TENANT_A).count() == 1
    assert Note.objects.using(TENANT_B).count() == 2


def test_tables_exist_only_where_they_belong():
    default_tables = connections["default"].introspection.table_names()
    tenant_tables = connections[TENANT_A].introspection.table_names()

    assert "accounts_user" in default_tables
    assert "organizations_organization" in default_tables
    assert "notes_note" not in default_tables

    assert "notes_note" in tenant_tables
    assert "accounts_user" not in tenant_tables
    assert "organizations_organization" not in tenant_tables
    assert "django_session" not in tenant_tables


def test_requests_see_only_their_own_tenant(client, org_a, org_b):
    client.force_login(org_a.owner)
    client.post("/notes/create/", {"title": "Alpha roadmap", "body": "secret"})
    assert "Alpha roadmap" in client.get("/").content.decode()
    client.post("/accounts/logout/")

    client.force_login(org_b.owner)
    page = client.get("/").content.decode()
    assert "Alpha roadmap" not in page
    assert Note.objects.using(TENANT_B).count() == 0


def test_ids_from_another_tenant_do_not_resolve(client, org_a, org_b):
    note = Note.objects.using(TENANT_A).create(title="Alpha only")

    client.force_login(org_b.owner)
    response = client.post(f"/notes/{note.id}/delete/")

    assert response.status_code == 404
    assert Note.objects.using(TENANT_A).filter(id=note.id).exists()


def test_tenant_context_is_cleared_after_each_request(client, org_a):
    client.force_login(org_a.owner)
    assert client.get("/").status_code == 200
    assert get_current_db() is None
