from django.conf import settings
from django.db import models


class GlobalSetting(models.Model):
    """Platform-wide key/value settings that can be changed without a deploy."""

    key = models.CharField(max_length=100, unique=True)
    value = models.TextField(default="")
    description = models.TextField(blank=True)

    def __str__(self):
        return self.key

    @classmethod
    def get(cls, key, default=""):
        value = cls.objects.filter(key=key).values_list("value", flat=True).first()
        return default if value is None else value

    @classmethod
    def set(cls, key, value, description=""):
        defaults = {"value": str(value)}
        if description:
            defaults["description"] = description
        cls.objects.update_or_create(key=key, defaults=defaults)


class RateLimitLog(models.Model):
    """One row each time the rate limiter refuses a request."""

    ip = models.GenericIPAddressField()
    endpoint = models.CharField(max_length=50)
    attempt_count = models.PositiveIntegerField(default=1)
    blocked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-blocked_at"]

    def __str__(self):
        return f"{self.ip} {self.endpoint}"


class BlockedIP(models.Model):
    """An IP address that is refused on every request."""

    ip = models.GenericIPAddressField(unique=True)
    reason = models.CharField(max_length=255, blank=True)
    blocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    blocked_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-blocked_at"]

    def __str__(self):
        return self.ip


class AuditLog(models.Model):
    """Licence changes, impersonation and other platform-admin actions."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    event = models.CharField(max_length=100)
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.event}: {self.message}"

    @classmethod
    def log(cls, event, message="", organization=None, actor=None):
        return cls.objects.create(
            event=event, message=message, organization=organization, actor=actor
        )
