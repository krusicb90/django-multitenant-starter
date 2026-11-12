from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path


def health(request):
    """Liveness and shared-database check used by Docker and the deploy script."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
    path("superadmin/", include("superadmin.urls")),
    path("accounts/", include("accounts.urls")),
    path("", include("organizations.urls")),
    path("", include("notes.urls")),
]
