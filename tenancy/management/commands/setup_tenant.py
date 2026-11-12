from django.core.management.base import BaseCommand, CommandError

from organizations.models import Organization
from tenancy.provisioning import provision_tenant


class Command(BaseCommand):
    help = "Create, migrate and seed the database of an organization (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("slug", help="Slug of the organization")

    def handle(self, *args, **options):
        try:
            organization = Organization.objects.get(slug=options["slug"])
        except Organization.DoesNotExist as error:
            raise CommandError(f'No organization with slug "{options["slug"]}"') from error
        alias = provision_tenant(organization)
        self.stdout.write(self.style.SUCCESS(f'Tenant database "{alias}" is ready'))
