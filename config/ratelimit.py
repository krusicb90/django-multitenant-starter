"""
Rate limiting for auth endpoints.

A fixed-window counter per client IP and endpoint, kept in Django's cache.
Limits come from settings.RATE_LIMITS and can be overridden at runtime with
GlobalSetting keys rl_<endpoint>_max and rl_<endpoint>_window.

Permanent IP blocks are a separate mechanism (superadmin.BlockedIPMiddleware).
"""

from django.conf import settings
from django.core.cache import cache

_FALLBACK = (5, 60 * 60)


def get_client_ip(request):
    """Client IP as seen behind Cloudflare and nginx."""
    cf_ip = request.META.get("HTTP_CF_CONNECTING_IP")
    if cf_ip:
        return cf_ip.strip()
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def get_limit(endpoint):
    """Return (max_attempts, window_seconds) for an endpoint."""
    from superadmin.models import GlobalSetting

    default_max, default_window = settings.RATE_LIMITS.get(endpoint, _FALLBACK)
    try:
        max_attempts = int(GlobalSetting.get(f"rl_{endpoint}_max", default_max))
        window = int(GlobalSetting.get(f"rl_{endpoint}_window", default_window))
    except (TypeError, ValueError):
        return default_max, default_window
    return max_attempts, window


def check_rate_limit(request, endpoint):
    """
    Count this attempt and tell whether the client is over the limit.

    Returns (blocked, message). When blocked is True the caller should refuse
    the request and show the message.
    """
    ip = get_client_ip(request)
    if not ip:
        return False, ""

    max_attempts, window = get_limit(endpoint)
    key = f"rl:{endpoint}:{ip}"
    count = cache.get(key, 0)

    if count >= max_attempts:
        _log_block(ip, endpoint, count + 1)
        minutes = max(1, window // 60)
        return True, f"Too many attempts. Try again in {minutes} minutes."

    try:
        cache.add(key, 0, window)
        cache.incr(key)
    except Exception:
        pass  # a cache failure must never break login or signup

    return False, ""


def _log_block(ip, endpoint, count):
    try:
        from superadmin.models import RateLimitLog

        RateLimitLog.objects.create(ip=ip, endpoint=endpoint, attempt_count=count)
    except Exception:
        pass
