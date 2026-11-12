"""Cloudflare Turnstile verification for login and registration forms."""

import json
import logging
import urllib.parse
import urllib.request

from django.conf import settings

from .ratelimit import get_client_ip

logger = logging.getLogger(__name__)

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify_turnstile(token, ip=None):
    """Return True when the token is valid, or when Turnstile is not configured."""
    secret = settings.TURNSTILE_SECRET_KEY
    if not secret:
        return True

    payload = {"secret": secret, "response": token}
    if ip:
        payload["remoteip"] = ip
    request = urllib.request.Request(
        VERIFY_URL, data=urllib.parse.urlencode(payload).encode(), method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return bool(json.loads(response.read()).get("success", False))
    except Exception:
        return False


def turnstile_bypassed(request):
    """True for client IPs listed in TURNSTILE_BYPASS_IPS (monitoring, end-to-end tests)."""
    allowed = settings.TURNSTILE_BYPASS_IPS
    return bool(allowed) and get_client_ip(request) in allowed


def turnstile_site_key(request):
    """Site key for the template; empty when the widget should not be rendered."""
    if turnstile_bypassed(request):
        return ""
    return settings.TURNSTILE_SITE_KEY


def turnstile_passed(request):
    if turnstile_bypassed(request):
        logger.warning("Turnstile bypass used for %s from %s", request.path, get_client_ip(request))
        return True
    return verify_turnstile(request.POST.get("cf-turnstile-response", ""), get_client_ip(request))
