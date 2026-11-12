import threading

import pytest
from django.db import router

from accounts.models import User
from notes.models import Note
from organizations.models import Organization
from tenancy.context import get_current_db, get_current_tenant, tenant_context
from tenancy.router import TenantContextMissing, TenantDatabaseRouter

from .conftest import TENANT_A, TENANT_B


def test_shared_models_use_the_default_database(org_a):
    assert router.db_for_read(User) == "default"
    assert router.db_for_write(Organization) == "default"
    with tenant_context(org_a):
        assert router.db_for_read(User) == "default"


def test_tenant_model_without_context_raises():
    with pytest.raises(TenantContextMissing):
        Note.objects.count()
    with pytest.raises(TenantContextMissing):
        Note.objects.create(title="lost")


def test_tenant_model_follows_the_active_tenant(org_a, org_b):
    with tenant_context(org_a):
        assert router.db_for_read(Note) == TENANT_A
        assert router.db_for_write(Note) == TENANT_A
    with tenant_context(org_b):
        assert router.db_for_read(Note) == TENANT_B


def test_nested_contexts_restore_the_outer_tenant(org_a, org_b):
    with tenant_context(org_a):
        with tenant_context(org_b):
            assert get_current_db() == TENANT_B
        assert get_current_db() == TENANT_A
        assert get_current_tenant() == org_a
    assert get_current_db() is None


def test_context_is_restored_after_an_exception(org_a):
    with pytest.raises(ValueError):
        with tenant_context(org_a):
            raise ValueError
    assert get_current_db() is None


def test_context_does_not_leak_into_other_threads(org_a):
    seen = []
    with tenant_context(org_a):
        thread = threading.Thread(target=lambda: seen.append(get_current_db()))
        thread.start()
        thread.join()
    assert seen == [None]


@pytest.mark.parametrize(
    ("db", "app_label", "expected"),
    [
        ("default", "accounts", True),
        ("default", "organizations", True),
        ("default", "auth", True),
        ("default", "sessions", True),
        ("default", "notes", False),
        (TENANT_A, "notes", True),
        (TENANT_A, "accounts", False),
        (TENANT_A, "auth", False),
        (TENANT_A, "contenttypes", False),
    ],
)
def test_allow_migrate(db, app_label, expected):
    assert TenantDatabaseRouter().allow_migrate(db, app_label) is expected


def test_relations_cannot_cross_between_shared_and_tenant_models(org_a):
    tenant_router = TenantDatabaseRouter()
    note = Note(title="x")
    assert tenant_router.allow_relation(org_a, org_a.owner) is True
    assert tenant_router.allow_relation(note, Note(title="y")) is True
    assert tenant_router.allow_relation(note, org_a.owner) is False
