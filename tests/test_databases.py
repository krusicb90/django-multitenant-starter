import pytest
from django.conf import settings
from django.db import connections

from notes.models import Note
from tenancy import databases
from tenancy.provisioning import deprovision_tenant, provision_tenant

postgres_only = pytest.mark.skipif(
    not settings.USE_POSTGRES, reason="needs PostgreSQL (TEST_DATABASE=postgres)"
)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "Tenant",
        "1tenant",
        "tenant-a",
        'tenant"; DROP DATABASE x; --',
        "tenant a",
        "t" * 64,
        None,
    ],
)
def test_unsafe_database_names_are_rejected(name):
    with pytest.raises(databases.InvalidDatabaseName):
        databases.validate_db_name(name)


def test_generated_names_are_valid_and_fit_postgres(plans, make_user):
    from organizations.models import Organization

    organization = Organization.objects.create(
        name=("Štefan & Sons — Zürich Office " + "x" * 80)[:100]
    )
    assert databases.validate_db_name(organization.db_name)
    assert len(organization.db_name) <= 63
    assert organization.db_name.startswith(settings.TENANT_DB_PREFIX)

    twin = Organization.objects.create(name=organization.name)
    assert twin.slug != organization.slug and twin.db_name != organization.db_name


def test_ensure_database_registers_a_copy_of_the_default(provisioning_sandbox):
    databases.ensure_database("tenant_runtime_1")
    config = connections.settings["tenant_runtime_1"]
    default = connections.settings["default"]

    assert config["ENGINE"] == default["ENGINE"]
    assert config["NAME"] != default["NAME"]
    assert config is not default and config["OPTIONS"] is not default["OPTIONS"]
    databases.ensure_database("tenant_runtime_1")  # idempotent


def test_provisioning_is_idempotent_and_seeds_once(plans, make_org, provisioning_sandbox):
    organization = make_org("Omega", "tenant_omega_11223344", ready=False)

    provision_tenant(organization)
    provision_tenant(organization)

    assert organization.db_ready
    assert Note.objects.using(organization.db_name).count() == 1

    deprovision_tenant(organization)
    assert organization.db_name not in connections.settings


@postgres_only
def test_create_exists_drop_round_trip():
    name = "tenant_roundtrip_55667788"
    assert not databases.database_exists(name)
    try:
        assert databases.create_database(name) is True
        assert databases.create_database(name) is False
        assert databases.database_exists(name)
    finally:
        assert databases.drop_database(name) is True
    assert databases.drop_database(name) is False
    assert not databases.database_exists(name)


@postgres_only
def test_drop_closes_open_connections(plans, make_org, provisioning_sandbox):
    organization = make_org("Busy", "tenant_busy_99aabbcc", ready=False)
    provision_tenant(organization)
    assert Note.objects.using(organization.db_name).count() == 1  # leaves a connection open

    deprovision_tenant(organization)
    assert not databases.database_exists(organization.db_name)


@postgres_only
def test_shared_databases_cannot_be_dropped():
    with pytest.raises(databases.InvalidDatabaseName):
        databases.drop_database(settings.DB_MAINTENANCE_NAME)
    with pytest.raises(databases.InvalidDatabaseName):
        databases.drop_database(connections.settings["default"]["NAME"])
