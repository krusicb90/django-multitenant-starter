"""
Test settings.

Three databases: the shared one and two tenant databases, so that isolation
between tenants is exercised against separate databases.

SQLite by default. Set TEST_DATABASE=postgres (plus the usual DB_* variables)
to run the same suite against PostgreSQL; this also enables the tests that
create and drop real tenant databases.
"""

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key")

from .settings import *  # noqa: E402, F403
from .settings import DATABASES  # noqa: E402

TEST_TENANT_ALIASES = ["tenant_test_a", "tenant_test_b"]
USE_POSTGRES = os.environ.get("TEST_DATABASE", "sqlite") == "postgres"

if USE_POSTGRES:
    for _alias in TEST_TENANT_ALIASES:
        DATABASES[_alias] = {**DATABASES["default"], "NAME": _alias}
else:
    DATABASES = {
        _alias: {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
        for _alias in ["default", *TEST_TENANT_ALIASES]
    }

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

EMAIL_ENABLED = True
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

SKIP_EMAIL_VERIFICATION = False
TURNSTILE_SITE_KEY = ""
TURNSTILE_SECRET_KEY = ""
TURNSTILE_BYPASS_IPS = []
ALLOWED_HOSTS = ["testserver", "localhost"]
SITE_URL = "http://testserver"
