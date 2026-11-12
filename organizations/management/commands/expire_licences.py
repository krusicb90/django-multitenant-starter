from django.core.management.base import BaseCommand

from organizations.licensing import expire_overdue


class Command(BaseCommand):
    help = "Mark ended trials and licences past their grace period as expired. Run daily."

    def handle(self, *args, **options):
        expired = expire_overdue()
        self.stdout.write(f"Expired {len(expired)} subscription(s)")
