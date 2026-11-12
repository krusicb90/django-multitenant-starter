import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class Plan(models.Model):
    """A licence tier. Limits of 0 mean unlimited."""

    name = models.CharField(max_length=50, unique=True)
    is_trial = models.BooleanField(default=False, help_text="The plan new signups start on.")
    user_limit = models.PositiveIntegerField(default=0, help_text="0 = unlimited")
    item_limit = models.PositiveIntegerField(
        default=0,
        help_text="Records in the tenant database (notes in the example app). 0 = unlimited",
    )
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price_yearly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "price_monthly"]

    def __str__(self):
        return self.name


class Organization(models.Model):
    """A tenant. Each organization has its own database, named in db_name."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)

    db_name = models.CharField(max_length=63, unique=True)
    db_ready = models.BooleanField(
        default=False, help_text="The tenant database has been created, migrated and seeded."
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_organizations",
        null=True,
        blank=True,
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._unique_slug()
        if not self.db_name:
            self.db_name = self._unique_db_name()
        super().save(*args, **kwargs)

    def _unique_slug(self):
        base = slugify(self.name)[:80] or "org"
        slug, counter = base, 1
        while Organization.objects.filter(slug=slug).exists():
            slug = f"{base}-{counter}"
            counter += 1
        return slug

    def _unique_db_name(self):
        # PostgreSQL identifiers hold 63 bytes: prefix + slug part + "_" + 8 hex chars.
        prefix = settings.TENANT_DB_PREFIX
        slug_part = "".join(c if c.isascii() and c.isalnum() else "_" for c in self.slug.lower())
        slug_part = slug_part[: 63 - len(prefix) - 9]
        while True:
            candidate = f"{prefix}{slug_part}_{uuid.uuid4().hex[:8]}"
            if not Organization.objects.filter(db_name=candidate).exists():
                return candidate

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    def user_count(self):
        return self.members.filter(is_active=True).count()

    def can_add_user(self):
        limit = self.plan.user_limit if self.plan else 0
        pending = self.invitations.filter(accepted=False, expires_at__gt=timezone.now()).count()
        return limit == 0 or self.user_count() + pending < limit

    def item_limit(self):
        return self.plan.item_limit if self.plan else 0


class Subscription(models.Model):
    """
    The licence of an organization: a trial, then paid terms that a platform
    admin activates and extends. Payment is handled outside the application.
    """

    class Status(models.TextChoices):
        TRIALING = "trialing", "Trial"
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    class Interval(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name="subscription"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIALING)
    interval = models.CharField(max_length=10, choices=Interval.choices, default=Interval.MONTHLY)

    trial_end = models.DateTimeField(null=True, blank=True)
    active_since = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.organization.name} - {self.status}"

    @staticmethod
    def grace_days():
        from superadmin.models import GlobalSetting

        try:
            return int(GlobalSetting.get("licence_grace_days", settings.LICENCE_GRACE_DAYS))
        except (TypeError, ValueError):
            return settings.LICENCE_GRACE_DAYS

    @property
    def is_valid(self):
        """Write access: a running trial, or an active licence within its term or grace period."""
        if self.status in (self.Status.CANCELLED, self.Status.EXPIRED):
            return False
        if self.status == self.Status.TRIALING:
            return not self.trial_end or self.trial_end >= timezone.now()
        if not self.valid_until:
            return True
        return timezone.localdate() <= self.valid_until + timedelta(days=self.grace_days())

    @property
    def in_grace(self):
        """An active licence whose term has ended but whose grace period has not."""
        if self.status != self.Status.ACTIVE or not self.valid_until:
            return False
        today = timezone.localdate()
        return self.valid_until < today <= self.valid_until + timedelta(days=self.grace_days())

    @property
    def end_date(self):
        if self.status == self.Status.TRIALING:
            return timezone.localtime(self.trial_end).date() if self.trial_end else None
        return self.valid_until

    @property
    def days_remaining(self):
        """Days until the trial or term ends (negative inside grace). None when open-ended."""
        if self.status == self.Status.TRIALING:
            if not self.trial_end:
                return None
            return max(0, (self.trial_end - timezone.now()).days)
        if self.status != self.Status.ACTIVE or not self.valid_until:
            return None
        return (self.valid_until - timezone.localdate()).days


def _invitation_token():
    return secrets.token_urlsafe(32)


def _invitation_expiry():
    return timezone.now() + timedelta(days=settings.INVITATION_VALID_DAYS)


class Invitation(models.Model):
    """An emailed invitation to join an organization."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField()
    role = models.CharField(max_length=20, default="member")
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sent_invitations",
    )
    token = models.CharField(max_length=64, unique=True, default=_invitation_token)

    accepted = models.BooleanField(default=False)
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_invitation_expiry)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "email"], name="unique_invitation_per_org_email"
            )
        ]

    def __str__(self):
        return f"{self.email} -> {self.organization.name}"

    @property
    def is_valid(self):
        return not self.accepted and self.expires_at > timezone.now()
