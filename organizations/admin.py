from django.contrib import admin

from .models import Invitation, Organization, Plan, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "is_trial", "user_limit", "item_limit", "price_monthly", "is_active")
    list_editable = ("is_active",)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "plan", "status", "db_name", "db_ready", "created_at")
    list_filter = ("status", "plan", "db_ready")
    search_fields = ("name", "slug", "db_name")
    readonly_fields = ("db_name", "db_ready", "created_at", "updated_at")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("organization", "status", "interval", "valid_until", "trial_end")
    list_filter = ("status", "interval")


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "organization", "role", "accepted", "expires_at")
    list_filter = ("accepted",)
    readonly_fields = ("token",)
