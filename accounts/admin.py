from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "email", "organization", "role", "is_active", "is_superuser")
    list_filter = ("role", "is_active", "is_superuser", "email_verified")
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Organization", {"fields": ("organization", "role", "is_org_owner", "email_verified")}),
    )
