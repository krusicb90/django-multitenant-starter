from django.urls import path

from . import views

urlpatterns = [
    # Signup
    path("register/", views.register, name="register"),
    path("registration-pending/", views.registration_pending, name="registration_pending"),
    path("verify-email/<str:token>/", views.verify_email, name="verify_email"),
    path("resend-verification/", views.resend_verification, name="resend_verification"),
    # Organization state
    path("organization-setup/", views.organization_setup, name="organization_setup"),
    path("organization-suspended/", views.organization_suspended, name="organization_suspended"),
    path("licence/", views.licence_status, name="licence_status"),
    # Members and invitations
    path("members/", views.members, name="members"),
    path("members/invite/", views.invite_member, name="invite_member"),
    path(
        "members/invitations/<int:invitation_id>/revoke/",
        views.revoke_invitation,
        name="revoke_invitation",
    ),
    path("members/<int:user_id>/deactivate/", views.deactivate_member, name="deactivate_member"),
    path("invitation/<str:token>/", views.invitation_accept, name="invitation_accept"),
]
