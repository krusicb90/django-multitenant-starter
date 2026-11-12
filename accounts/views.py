from django.contrib import messages
from django.contrib.auth import views as auth_views

from config.ratelimit import check_rate_limit
from config.turnstile import turnstile_passed, turnstile_site_key


class LoginView(auth_views.LoginView):
    """Django's login view behind the rate limiter and Turnstile."""

    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        blocked, message = check_rate_limit(request, "login")
        if blocked:
            messages.error(request, message)
            return self.render_to_response(self.get_context_data(), status=429)
        if not turnstile_passed(request):
            messages.error(request, "Verification failed. Please try again.")
            return self.render_to_response(self.get_context_data(), status=400)
        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["turnstile_site_key"] = turnstile_site_key(self.request)
        return context
