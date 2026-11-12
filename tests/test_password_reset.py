import re

from django.core import mail

from accounts.models import User

from .conftest import PASSWORD


def test_password_reset_flow(client, org_a):
    owner = org_a.owner
    assert client.post("/accounts/password-reset/", {"email": owner.email}).status_code == 302
    assert len(mail.outbox) == 1
    link = re.search(r"http://testserver(/accounts/reset/\S+)", mail.outbox[0].body).group(1)

    form_page = client.get(link, follow=True)
    assert form_page.status_code == 200
    new_password = "a-new-long-passphrase"
    done = client.post(
        form_page.request["PATH_INFO"],
        {"new_password1": new_password, "new_password2": new_password},
    )
    assert done.url == "/accounts/reset/done/"

    owner = User.objects.get(id=owner.id)
    assert owner.check_password(new_password) and not owner.check_password(PASSWORD)
    assert client.get(link, follow=True).content.decode().count("invalid or has already been used")


def test_password_reset_does_not_reveal_unknown_addresses(client, db):
    response = client.post("/accounts/password-reset/", {"email": "nobody@example.com"})
    assert response.url == "/accounts/password-reset/done/"
    assert len(mail.outbox) == 0
