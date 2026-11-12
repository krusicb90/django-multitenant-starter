from .models import Note


def create_welcome_note(organization, alias):
    """Seed hook (settings.TENANT_SEED_HOOKS): runs once in a new tenant database."""
    Note.objects.using(alias).create(
        title=f"Welcome to {organization.name}",
        body="This note lives in your organization's own database.",
        author_name="System",
    )
