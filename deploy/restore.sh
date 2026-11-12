#!/usr/bin/env bash
# Restore databases from an archive made by backup.sh.
#
#   restore.sh <archive.tar.gz> --list                      show what the archive contains
#   restore.sh <archive.tar.gz> --yes                       restore ALL databases in the archive
#   restore.sh <archive.tar.gz> --yes --db tenant_acme_1a2b restore only the named database(s)
#
# Each restored database is dropped and recreated from its dump. Restoring a
# single tenant leaves the shared database and all other tenants untouched.
set -euo pipefail

USAGE="Usage: restore.sh <archive.tar.gz> [--list] [--yes] [--db name ...]"
[[ -f "${1:-}" ]] || { echo "$USAGE"; exit 1; }
ARCHIVE="$(realpath "$1")"; shift

APP_DIR="${APP_DIR:-/opt/app}"
cd "$APP_DIR"
set -a
# shellcheck source=/dev/null
source .env
set +a

PG_IMAGE="${PG_IMAGE:-postgres:16-alpine}"
DB_MAINTENANCE_NAME="${DB_MAINTENANCE_NAME:-postgres}"
DB_PORT="${DB_PORT:-5432}"

CONFIRM=0; LIST=0; ONLY_DBS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes) CONFIRM=1 ;;
        --list) LIST=1 ;;
        --db) shift; [[ $# -gt 0 ]] || { echo "$USAGE"; exit 1; }; ONLY_DBS+=("$1") ;;
        *) echo "Unknown argument: $1"; echo "$USAGE"; exit 1 ;;
    esac
    shift
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
pg() {
    docker run --rm -i --network host \
        -e PGPASSWORD="$DB_PASSWORD" -e PGSSLMODE="${DB_SSLMODE:-require}" \
        "$PG_IMAGE" "$@"
}
WORK="$(mktemp -d /tmp/app-restore.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

if [[ -f "$ARCHIVE.sha256" ]]; then
    ( cd "$(dirname "$ARCHIVE")" && sha256sum -c "$(basename "$ARCHIVE").sha256" ) || { log "ERROR: checksum mismatch"; exit 1; }
fi
tar -xzf "$ARCHIVE" -C "$WORK"

if [[ $LIST -eq 1 ]]; then
    echo "Image tag at backup time: $(cat "$WORK/IMAGE_TAG.txt" 2>/dev/null || echo unknown)"
    echo "Databases:"; sed 's/^/  /' "$WORK/db/DATABASES.txt"
    exit 0
fi

[[ $CONFIRM -eq 1 ]] || { echo "Refusing to restore without --yes (this DROPS and recreates databases)."; exit 1; }

if [[ ${#ONLY_DBS[@]} -gt 0 ]]; then
    DBS=("${ONLY_DBS[@]}")
else
    mapfile -t DBS < "$WORK/db/DATABASES.txt"
fi
for db in "${DBS[@]}"; do
    [[ "$db" =~ ^[a-z][a-z0-9_]*$ ]] || { log "ERROR: invalid database name: $db"; exit 1; }
    [[ -f "$WORK/db/${db}.dump" ]] || { log "ERROR: no dump for $db in the archive"; exit 1; }
done

log "Stopping application containers"
docker compose stop web cron >/dev/null

for db in "${DBS[@]}"; do
    log "Restoring $db"
    pg psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_MAINTENANCE_NAME" -q -c \
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$db' AND pid <> pg_backend_pid();" >/dev/null || true
    pg pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_MAINTENANCE_NAME" \
        --clean --create --if-exists --no-owner --no-privileges --exit-on-error < "$WORK/db/${db}.dump"
done

log "Starting application containers"
docker compose up -d web cron >/dev/null
log "Restore complete. Check: docker logs -f app-web"
