from django.core.management.base import BaseCommand

from organizations.licensing import seed_plans


class Command(BaseCommand):
    help = "Create the trial plan and the example tiers if they do not exist."

    def handle(self, *args, **options):
        created = seed_plans()
        self.stdout.write(f"Plans created: {', '.join(created) if created else 'none'}")
