from django.core.management.base import BaseCommand, CommandError

from tenancy.databases import InvalidDatabaseName, create_database, is_postgres


class Command(BaseCommand):
    help = "Create an empty PostgreSQL database for a tenant."

    def add_arguments(self, parser):
        parser.add_argument("db_name")

    def handle(self, *args, **options):
        db_name = options["db_name"]
        if not is_postgres():
            self.stdout.write("Not PostgreSQL: SQLite tenant files are created on first use.")
            return
        try:
            created = create_database(db_name)
        except InvalidDatabaseName as error:
            raise CommandError(str(error)) from error
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created database "{db_name}"'))
        else:
            self.stdout.write(f'Database "{db_name}" already exists')
