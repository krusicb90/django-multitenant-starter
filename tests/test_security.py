from django.test import RequestFactory

from config import turnstile
from config.ratelimit import check_rate_limit, get_client_ip, get_limit
from superadmin.models import BlockedIP, GlobalSetting, RateLimitLog

from .conftest import PASSWORD


def request_from(ip, **headers):
    return RequestFactory().post("/accounts/login/", REMOTE_ADDR=ip, **headers)


def test_client_ip_prefers_cloudflare_then_forwarded_for():
    assert get_client_ip(request_from("10.0.0.1")) == "10.0.0.1"
    assert (
        get_client_ip(request_from("10.0.0.1", HTTP_X_FORWARDED_FOR="198.51.100.7, 10.0.0.2"))
        == "198.51.100.7"
    )
    assert (
        get_client_ip(
            request_from(
                "10.0.0.1",
                HTTP_X_FORWARDED_FOR="198.51.100.7",
                HTTP_CF_CONNECTING_IP="203.0.113.9",
            )
        )
        == "203.0.113.9"
    )


def test_rate_limit_blocks_after_the_allowed_attempts(settings):
    settings.RATE_LIMITS = {"login": (3, 600)}
    request = request_from("203.0.113.5")

    assert [check_rate_limit(request, "login")[0] for _ in range(4)] == [False, False, False, True]
    blocked, message = check_rate_limit(request, "login")
    assert blocked and "10 minutes" in message
    assert RateLimitLog.objects.filter(ip="203.0.113.5", endpoint="login").count() == 2


def test_rate_limit_is_counted_per_ip_and_per_endpoint(settings):
    settings.RATE_LIMITS = {"login": (1, 600), "register": (1, 600)}
    first, second = request_from("203.0.113.5"), request_from("203.0.113.6")

    assert check_rate_limit(first, "login")[0] is False
    assert check_rate_limit(first, "login")[0] is True
    assert check_rate_limit(second, "login")[0] is False
    assert check_rate_limit(first, "register")[0] is False


def test_limits_can_be_overridden_at_runtime(settings):
    settings.RATE_LIMITS = {"login": (10, 900)}
    assert get_limit("login") == (10, 900)
    GlobalSetting.set("rl_login_max", 2)
    GlobalSetting.set("rl_login_window", 60)
    assert get_limit("login") == (2, 60)
    GlobalSetting.set("rl_login_max", "not a number")
    assert get_limit("login") == (10, 900)


def test_login_is_rate_limited(client, org_a, settings):
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "login": (2, 900)}
    wrong = {"username": org_a.owner.username, "password": "wrong"}

    assert client.post("/accounts/login/", wrong).status_code == 200
    assert client.post("/accounts/login/", wrong).status_code == 200
    response = client.post(
        "/accounts/login/", {"username": org_a.owner.username, "password": PASSWORD}
    )
    assert response.status_code == 429
    assert "_auth_user_id" not in client.session


def test_turnstile_is_skipped_without_a_secret(settings):
    settings.TURNSTILE_SECRET_KEY = ""
    assert turnstile.verify_turnstile("anything") is True


def test_login_requires_turnstile_when_configured(client, org_a, settings, monkeypatch):
    settings.TURNSTILE_SITE_KEY = "site-key"
    settings.TURNSTILE_SECRET_KEY = "secret-key"
    credentials = {"username": org_a.owner.username, "password": PASSWORD}

    monkeypatch.setattr(turnstile, "verify_turnstile", lambda token, ip=None: False)
    assert 'data-sitekey="site-key"' in client.get("/accounts/login/").content.decode()
    assert client.post("/accounts/login/", credentials).status_code == 400
    assert "_auth_user_id" not in client.session

    monkeypatch.setattr(turnstile, "verify_turnstile", lambda token, ip=None: token == "good")
    response = client.post("/accounts/login/", {**credentials, "cf-turnstile-response": "good"})
    assert response.status_code == 302


def test_turnstile_bypass_applies_only_to_listed_ips(client, org_a, settings, monkeypatch):
    settings.TURNSTILE_SITE_KEY = "site-key"
    settings.TURNSTILE_SECRET_KEY = "secret-key"
    settings.TURNSTILE_BYPASS_IPS = ["203.0.113.50"]
    monkeypatch.setattr(turnstile, "verify_turnstile", lambda token, ip=None: False)
    credentials = {"username": org_a.owner.username, "password": PASSWORD}

    page = client.get("/accounts/login/", REMOTE_ADDR="203.0.113.50").content.decode()
    assert "data-sitekey" not in page
    assert (
        client.post("/accounts/login/", credentials, REMOTE_ADDR="203.0.113.51").status_code == 400
    )
    assert (
        client.post("/accounts/login/", credentials, REMOTE_ADDR="203.0.113.50").status_code == 302
    )


def test_blocked_ip_is_refused_everywhere(client):
    BlockedIP.objects.create(ip="203.0.113.99")

    assert client.get("/accounts/login/", REMOTE_ADDR="203.0.113.99").status_code == 403
    assert client.get("/health/", REMOTE_ADDR="203.0.113.99").status_code == 403
    assert client.get("/accounts/login/", REMOTE_ADDR="203.0.113.98").status_code == 200

    BlockedIP.objects.update(is_active=False)
    assert client.get("/accounts/login/", REMOTE_ADDR="203.0.113.99").status_code == 200
