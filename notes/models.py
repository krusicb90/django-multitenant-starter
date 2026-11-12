from django.db import models


class Note(models.Model):
    """
    Example tenant model. Its table exists once per tenant database.

    Users live in the shared database and foreign keys cannot cross databases,
    so the author is stored as a plain id plus a display name.
    """

    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    author_id = models.BigIntegerField(null=True, blank=True)
    author_name = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.title
