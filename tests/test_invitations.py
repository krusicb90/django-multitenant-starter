from datetime import timedelta

from django.core import mail
from django.utils import timezone

from accounts.models import User
from organizations.models import Invitation

from .conftest import PASSWORD

ACCEPT = {
    "first_name": "Grace",
    "last_name": "Hopper",
    "password1": PASSWORD,
    "password2": PASSWORD,
}


def invite(client, organization, email="grace@alpha.example", role="member"):
    client.force_login(organization.owner)
    client.post("/members/invite/", {"email": email, "role": role})
    client.post("/accounts/logout/")
    return Invitation.objects.filter(email=email).first()


def test_admin_can_invite_and_the_email_carries_the_link(client, org_a):
    invitation = invite(client, org_a)

    assert invitation.organization == org_a
    assert invitation.invited_by == org_a.owner
    assert invitation.is_valid
    assert len(mail.outbox) == 1
    assert f"/invitation/{invitation.token}/" in mail.outbox[0].body


def test_member_cannot_invite(client, org_a, make_user):
    client.force_login(make_user("member@alpha.example", organization=org_a))
    response = client.post("/members/invite/", {"email": "x@alpha.example", "role": "admin"})
    assert response.status_code == 403
    assert Invitation.objects.count() == 0


def test_accepting_creates_a_member_of_the_inviting_organization(client, org_a, org_b):
    invitation = invite(client, org_a, role="readonly")

    response = client.post(f"/invitation/{invitation.token}/", ACCEPT)
    assert response.url == "/"

    user = User.objects.get(username="grace@alpha.example")
    assert user.organization == org_a
    assert user.role == "readonly"
    assert user.email_verified and not user.is_org_owner
    assert client.get("/").wsgi_request.organization == org_a


def test_invitation_works_once(client, org_a):
    invitation = invite(client, org_a)
    client.post(f"/invitation/{invitation.token}/", ACCEPT)
    client.post("/accounts/logout/")

    assert client.get(f"/invitation/{invitation.token}/").status_code == 400
    assert client.post(f"/invitation/{invitation.token}/", ACCEPT).status_code == 400
    assert User.objects.filter(username="grace@alpha.example").count() == 1


def test_expired_and_unknown_invitations_are_rejected(client, org_a):
    invitation = invite(client, org_a)
    Invitation.objects.filter(id=invitation.id).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )

    assert client.post(f"/invitation/{invitation.token}/", ACCEPT).status_code == 400
    assert client.get("/invitation/unknown-token/").status_code == 400
    assert not User.objects.filter(username="grace@alpha.example").exists()


def test_user_limit_counts_members_and_pending_invitations(client, org_a, plans):
    plans["Trial"].user_limit = 2
    plans["Trial"].save()

    assert invite(client, org_a, "first@alpha.example") is not None
    assert invite(client, org_a, "second@alpha.example") is None


def test_existing_user_cannot_be_invited(client, org_a, org_b):
    assert invite(client, org_a, org_b.owner.email) is None


def test_invitations_of_another_organization_cannot_be_revoked(client, org_a, org_b):
    invitation = invite(client, org_a)

    client.force_login(org_b.owner)
    assert client.post(f"/members/invitations/{invitation.id}/revoke/").status_code == 404
    client.post("/accounts/logout/")

    client.force_login(org_a.owner)
    assert client.post(f"/members/invitations/{invitation.id}/revoke/").url == "/members/"
    assert not Invitation.objects.filter(id=invitation.id).exists()


def test_members_page_lists_only_the_own_organization(client, org_a, org_b):
    client.force_login(org_a.owner)
    page = client.get("/members/").content.decode()
    assert org_a.owner.email in page
    assert org_b.owner.email not in page


def test_members_of_another_organization_cannot_be_deactivated(client, org_a, org_b, make_user):
    victim = make_user("victim@beta.example", organization=org_b)
    colleague = make_user("colleague@alpha.example", organization=org_a)
    client.force_login(org_a.owner)

    assert client.post(f"/members/{victim.id}/deactivate/").status_code == 404
    client.post(f"/members/{colleague.id}/deactivate/")
    client.post(f"/members/{org_a.owner.id}/deactivate/")

    assert User.objects.get(id=victim.id).is_active
    assert not User.objects.get(id=colleague.id).is_active
    assert User.objects.get(id=org_a.owner.id).is_active
