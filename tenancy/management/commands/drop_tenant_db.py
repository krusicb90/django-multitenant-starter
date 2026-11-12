from django.core.management.base import BaseCommand, CommandError

from tenancy.databases import InvalidDatabaseName, drop_database, forget_database, is_postgres


class Command(BaseCommand):
    help = "Drop a tenant's PostgreSQL database. This cannot be undone."

    def add_arguments(self, parser):
        parser.add_argument("db_name")
        parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation")

    def handle(self, *args, **options):
        db_name = options["db_name"]
        if not is_postgres():
            raise CommandError("This command works on PostgreSQL only.")
        if not options["yes"]:
            answer = input(f'Type the database name to drop "{db_name}": ')
            if answer != db_name:
                raise CommandError("Aborted.")
        try:
            forget_database(db_name)
            dropped = drop_database(db_name)
        except InvalidDatabaseName as error:
            raise CommandError(str(error)) from error
        if dropped:
            self.stdout.write(self.style.SUCCESS(f'Dropped database "{db_name}"'))
        else:
            self.stdout.write(f'Database "{db_name}" does not exist')
