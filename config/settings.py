"""
Django settings.

Everything environment-specific is read from environment variables; see
.env.example for local development and deploy/.env.production.example for
production.
"""

import os
from pathlib import Path

from django.contrib.messages import constants as messages
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY environment variable is required")

DEBUG = env_bool("DEBUG")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

# nginx terminates TLS and forwards X-Forwarded-Proto, so that
# request.build_absolute_uri() produces https:// links.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# --- Applications -----------------------------------------------------------

# App labels whose tables live in each tenant's own database. Every other app
# is shared and lives in the "default" database. See tenancy/router.py.
TENANT_APPS = ["notes"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # shared database
    "accounts",
    "organizations",
    "superadmin",
    "tenancy",
    # tenant databases
    "notes",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "superadmin.middleware.BlockedIPMiddleware",  # reject blocked IPs before anything else
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "superadmin.middleware.ImpersonationMiddleware",  # after auth, before tenant
    "tenancy.middleware.TenantMiddleware",  # after auth and messages
    "organizations.middleware.SubscriptionMiddleware",  # after tenant
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "organizations.context_processors.tenant",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# --- Databases --------------------------------------------------------------

# "default" is the shared database: users, organizations, plans, licences.
# Tenant databases are not listed here. They are created at signup and
# registered at runtime under an alias equal to the database name.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "app_main"),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "OPTIONS": {"sslmode": os.environ.get("DB_SSLMODE", "prefer")},
    }
}

DATABASE_ROUTERS = ["tenancy.router.TenantDatabaseRouter"]

# Database to connect to when running CREATE DATABASE / DROP DATABASE.
# "postgres" on a self-hosted server; managed services often use another name.
DB_MAINTENANCE_NAME = os.environ.get("DB_MAINTENANCE_NAME", "postgres")

# Prefix of every tenant database name.
TENANT_DB_PREFIX = os.environ.get("TENANT_DB_PREFIX", "tenant_")

# Callables run once against a freshly migrated tenant database:
# func(organization, alias).
TENANT_SEED_HOOKS = ["notes.seed.create_welcome_note"]


# --- Cache ------------------------------------------------------------------

# The rate limiter counts attempts in the cache. With the in-memory backend
# every gunicorn worker counts on its own, so set REDIS_URL in production.
REDIS_URL = os.environ.get("REDIS_URL", "")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


# --- Auth -------------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# --- Internationalization ---------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True


# --- Static files -----------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MESSAGE_TAGS = {
    messages.DEBUG: "secondary",
    messages.INFO: "info",
    messages.SUCCESS: "success",
    messages.WARNING: "warning",
    messages.ERROR: "danger",
}


# --- Security ---------------------------------------------------------------

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

if not DEBUG:
    if env_bool("USE_HTTPS"):
        CSRF_COOKIE_SECURE = True
        SESSION_COOKIE_SECURE = True
        # SECURE_SSL_REDIRECT is left off on purpose: nginx redirects HTTP to
        # HTTPS and Django only ever sees plain HTTP from the proxy.
        SECURE_HSTS_SECONDS = 31536000
        SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# Cloudflare Turnstile on login and registration. Disabled while the secret
# key is empty.
TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "")
TURNSTILE_BYPASS_IPS = env_list("TURNSTILE_BYPASS_IPS")

# Rate limits for auth endpoints: (attempts, window in seconds). Each value
# can be overridden at runtime from the superadmin panel (GlobalSetting).
RATE_LIMITS = {
    "login": (10, 15 * 60),
    "register": (5, 60 * 60),
    "resend": (5, 60 * 60),
}


# --- Trials and licences ----------------------------------------------------

TRIAL_PERIOD_DAYS = int(os.environ.get("TRIAL_PERIOD_DAYS", "30"))
TRIAL_REMINDER_DAYS = [7, 3, 1]

LICENCE_GRACE_DAYS = int(os.environ.get("LICENCE_GRACE_DAYS", "7"))
LICENCE_REMINDER_DAYS = [30, 7, 1]

INVITATION_VALID_DAYS = 7

# Local development: activate new accounts without the verification email.
SKIP_EMAIL_VERIFICATION = env_bool("SKIP_EMAIL_VERIFICATION")


# --- Email ------------------------------------------------------------------

EMAIL_ENABLED = env_bool("EMAIL_ENABLED", True)
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL")
EMAIL_TIMEOUT = 15  # keeps a hung SMTP server from tying up a gunicorn worker
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@example.com")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# Used when EMAIL_BACKEND=config.mailgun_backend.MailgunBackend
MAILGUN_API_KEY = os.environ.get("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.environ.get("MAILGUN_DOMAIN", "")
MAILGUN_BASE_URL = os.environ.get("MAILGUN_BASE_URL", "https://api.mailgun.net")

# Base URL used in links inside emails.
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000").rstrip("/")
SITE_NAME = os.environ.get("SITE_NAME", "Starter")


# --- Logging ----------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "[%(levelname)s %(asctime)s %(name)s] %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
        "null": {"class": "logging.NullHandler"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO" if DEBUG else "WARNING",
            "propagate": False,
        },
        # Scanners sending random Host headers are not actionable.
        "django.security.DisallowedHost": {"handlers": ["null"], "propagate": False},
    },
}
