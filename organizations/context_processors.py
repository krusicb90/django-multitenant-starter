from django.conf import settings


def tenant(request):
    organization = getattr(request, "organization", None)
    return {
        "site_name": settings.SITE_NAME,
        "organization": organization,
        "subscription": getattr(organization, "subscription", None) if organization else None,
        "org_read_only": getattr(request, "org_read_only", False),
        "impersonator": getattr(request, "impersonator", None),
    }
