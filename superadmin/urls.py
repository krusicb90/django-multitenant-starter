from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="superadmin_dashboard"),
    path("organizations/<int:org_id>/", views.organization_detail, name="superadmin_organization"),
    path(
        "organizations/<int:org_id>/action/",
        views.organization_action,
        name="superadmin_organization_action",
    ),
    path(
        "organizations/<int:org_id>/delete/",
        views.organization_delete,
        name="superadmin_organization_delete",
    ),
    path("impersonate/<int:user_id>/", views.impersonate, name="superadmin_impersonate"),
    path("stop-impersonation/", views.stop_impersonation, name="superadmin_stop_impersonation"),
    path("blocked-ips/", views.blocked_ips, name="superadmin_blocked_ips"),
]
