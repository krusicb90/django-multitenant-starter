import pytest
from django.conf import settings
from django.core.cache import cache
from django.db import connections

from accounts.models import User
from organizations import licensing
from organizations.models import Organization, Plan
from tenancy.context import deactivate
from tenancy.databases import drop_database, forget_database, is_postgres

PASSWORD = "pw-Test-12345"
TENANT_A, TENANT_B = settings.TEST_TENANT_ALIASES


def pytest_collection_modifyitems(items):
    # Every test may touch the shared database and both tenant databases.
    for item in items:
        item.add_marker(pytest.mark.django_db(databases="__all__"))


@pytest.fixture(autouse=True)
def clean_state():
    cache.clear()
    deactivate()
    yield
    deactivate()


@pytest.fixture
def plans():
    licensing.seed_plans()
    return {plan.name: plan for plan in Plan.objects.all()}


@pytest.fixture
def make_user():
    def factory(email, organization=None, role=User.Role.MEMBER, **extra):
        return User.objects.create_user(
            username=email,
            email=email,
            password=PASSWORD,
            organization=organization,
            role=role,
            email_verified=True,
            **extra,
        )

    return factory


@pytest.fixture
def make_org(plans, make_user):
    """An organization on the trial plan with an owner, bound to a test tenant database."""

    def factory(name, alias, ready=True):
        owner = make_user(f"owner@{name.lower()}.example", role=User.Role.ADMIN, is_org_owner=True)
        organization = Organization.objects.create(
            name=name, db_name=alias, db_ready=ready, owner=owner, plan=plans["Trial"]
        )
        owner.organization = organization
        owner.save(update_fields=["organization"])
        licensing.start_trial(organization)
        return organization

    return factory


@pytest.fixture
def org_a(make_org):
    return make_org("Alpha", TENANT_A)


@pytest.fixture
def org_b(make_org):
    return make_org("Beta", TENANT_B)


@pytest.fixture
def superadmin(db):
    return User.objects.create_superuser("root", "root@platform.example", PASSWORD)


@pytest.fixture
def provisioning_sandbox(settings, tmp_path, django_db_blocker):
    """
    Lets a test run real tenant provisioning. SQLite tenant files go to a
    temporary directory; databases created on PostgreSQL are dropped afterwards.
    """
    settings.BASE_DIR = tmp_path
    known = set(connections.settings)
    # Django's test framework refuses connections to databases that were not
    # declared when the test started. Provisioning creates one, so that guard
    # is lifted for these tests.
    with django_db_blocker.unblock():
        yield
        for alias in set(connections.settings) - known:
            forget_database(alias)
            if is_postgres():
                drop_database(alias)
