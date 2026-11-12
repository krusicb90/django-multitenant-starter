from django.contrib.auth import get_user_model
from django.http import HttpResponseForbidden

from config.ratelimit import get_client_ip

IMPERSONATED_SESSION_KEY = "_impersonated_user_id"


class BlockedIPMiddleware:
    """
    Refuses requests from addresses in the BlockedIP table. Placed right after
    SecurityMiddleware so that blocked clients cost as little as possible.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .models import BlockedIP

        ip = get_client_ip(request)
        if ip and BlockedIP.objects.filter(ip=ip, is_active=True).exists():
            return HttpResponseForbidden("403 Forbidden", content_type="text/plain")
        return self.get_response(request)


class ImpersonationMiddleware:
    """
    Lets a platform superadmin act as a member of an organization.

    While the session holds an impersonated user id, request.user is replaced
    by that user and the real superadmin is kept in request.impersonator.
    Runs before TenantMiddleware, so the tenant database follows the
    impersonated user.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.impersonator = None
        impersonated_id = request.session.get(IMPERSONATED_SESSION_KEY)

        if impersonated_id:
            real_user = request.user
            target = None
            # Only a superadmin's session may carry the key.
            if real_user.is_authenticated and real_user.is_superuser:
                target = get_user_model().objects.filter(id=impersonated_id).first()
            if target is None:
                request.session.pop(IMPERSONATED_SESSION_KEY, None)
            else:
                request.impersonator = real_user
                request.user = target

        return self.get_response(request)
