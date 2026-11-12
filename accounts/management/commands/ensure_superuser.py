import os

from django.core.management.base import BaseCommand

from accounts.models import User


class Command(BaseCommand):
    help = "Create the platform superadmin from SUPERUSER_* variables if it does not exist."

    def handle(self, *args, **options):
        username = os.environ.get("SUPERUSER_USERNAME")
        email = os.environ.get("SUPERUSER_EMAIL")
        password = os.environ.get("SUPERUSER_PASSWORD")
        if not (username and email and password):
            self.stdout.write("SUPERUSER_* not set, skipping")
            return
        if User.objects.filter(username=username).exists():
            self.stdout.write("Superuser already exists")
            return
        User.objects.create_superuser(
            username, email, password, role=User.Role.ADMIN, email_verified=True
        )
        self.stdout.write(self.style.SUCCESS(f"Created superuser {username}"))
