from django.conf import settings
from django.core.management.base import BaseCommand

from accounts.emails import send_licence_reminder
from organizations.licensing import licences_ending_in, trials_ending_in


class Command(BaseCommand):
    help = "Email owners whose trial or licence ends in a configured number of days. Run daily."

    def handle(self, *args, **options):
        sent = 0
        for days in settings.TRIAL_REMINDER_DAYS:
            for subscription in trials_ending_in(days):
                sent += send_licence_reminder(subscription.organization, "trial", days)
        for days in settings.LICENCE_REMINDER_DAYS:
            for subscription in licences_ending_in(days):
                sent += send_licence_reminder(subscription.organization, "licence", days)
        self.stdout.write(f"Sent {sent} reminder(s)")
