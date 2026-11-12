#!/bin/sh
# Prepares the databases, then runs the container command (gunicorn by default).
set -eu

echo "Waiting for the database at ${DB_HOST:-localhost}:${DB_PORT:-5432}..."
python - <<'PY'
import os
import sys
import time

import psycopg2

for attempt in range(1, 31):
    try:
        psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            port=os.environ.get("DB_PORT", "5432"),
            dbname=os.environ.get("DB_NAME", "app_main"),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", ""),
            sslmode=os.environ.get("DB_SSLMODE", "prefer"),
            connect_timeout=5,
        ).close()
        sys.exit(0)
    except psycopg2.OperationalError as error:
        print(f"  not ready ({attempt}/30): {str(error).strip().splitlines()[0]}")
        time.sleep(2)
sys.exit("Database did not become ready")
PY

echo "Migrating the shared database..."
python manage.py migrate --noinput

# Fails the start if any tenant database cannot be migrated, so that a broken
# release never serves traffic. deploy.sh then rolls back to the previous image.
echo "Migrating tenant databases..."
python manage.py migrate_tenants

python manage.py seed_plans
python manage.py ensure_superuser

echo "Collecting static files..."
python manage.py collectstatic --noinput

exec "$@"
