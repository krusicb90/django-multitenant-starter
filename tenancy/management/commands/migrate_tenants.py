from django.core.management.base import BaseCommand, CommandError

from tenancy.provisioning import migrate_all_tenants


class Command(BaseCommand):
    help = "Apply tenant-app migrations to every provisioned tenant database."

    def handle(self, *args, **options):
        migrated, failed = migrate_all_tenants(stdout=self.stdout, verbosity=0)
        self.stdout.write(f"Migrated {len(migrated)} tenant database(s)")
        if failed:
            # A non-zero exit stops the container from starting on a half-migrated fleet.
            raise CommandError(f"{len(failed)} tenant database(s) failed: {', '.join(failed)}")
