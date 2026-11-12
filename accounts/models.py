import secrets

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    A user belongs to at most one organization. Users live in the shared
    database; platform superadmins have no organization.
    """

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"
        READONLY = "readonly", "Read-only"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="members",
    )
    is_org_owner = models.BooleanField(default=False)

    email_verified = models.BooleanField(default=False)
    email_verification_token = models.CharField(max_length=64, blank=True, default="")
    email_verification_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["first_name", "last_name", "username"]

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def is_org_admin(self):
        return self.is_org_owner or self.role == self.Role.ADMIN

    def new_verification_token(self):
        self.email_verification_token = secrets.token_urlsafe(32)
        return self.email_verification_token
