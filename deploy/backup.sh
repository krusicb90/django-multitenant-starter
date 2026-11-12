#!/usr/bin/env bash
# Logical backup of the whole PostgreSQL server: the shared database and every
# tenant database, each as its own pg_dump file, so that a single tenant can be
# restored without touching the others.
#
# PostgreSQL client tools run from the ${PG_IMAGE} container, so pg_dump always
# matches the server's major version and nothing has to be installed on the host.
#
# Output: ${APP_DIR}/backups/<kind>/backup-<kind>-YYYYmmdd-HHMMSS.tar.gz (+ .sha256)
# Optional off-site copy with rclone (BACKUP_RCLONE_REMOTE in .env).
#
# Env overrides: BACKUP_KIND=daily|predeploy  BACKUP_SKIP_REMOTE=1
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/app}"
cd "$APP_DIR"
set -a
# shellcheck source=/dev/null
source .env
set +a

PG_IMAGE="${PG_IMAGE:-postgres:16-alpine}"
DB_MAINTENANCE_NAME="${DB_MAINTENANCE_NAME:-postgres}"
DB_PORT="${DB_PORT:-5432}"
BACKUP_ROOT="$APP_DIR/backups"
KIND="${BACKUP_KIND:-daily}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
WEEKLY_KEEP="${BACKUP_WEEKLY_KEEP:-8}"
PREDEPLOY_KEEP=5
REMOTE="${BACKUP_RCLONE_REMOTE:-}"
NAME="backup-${KIND}-$(date +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d /tmp/app-backup.XXXXXX)"
LOCK=/var/lock/app-backup.lock

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
trap 'rm -rf "$WORK"' EXIT

# Run a PostgreSQL client tool (psql, pg_dump, pg_dumpall) against the server.
pg() {
    docker run --rm -i --network host \
        -e PGPASSWORD="$DB_PASSWORD" -e PGSSLMODE="${DB_SSLMODE:-require}" \
        "$PG_IMAGE" "$@"
}

exec 9>"$LOCK"
flock -n 9 || { log "another backup is running, exiting"; exit 0; }

: "${DB_HOST:?DB_HOST missing in .env}" "${DB_USER:?DB_USER missing in .env}" "${DB_PASSWORD:?DB_PASSWORD missing in .env}"

mkdir -p "$WORK/db" "$BACKUP_ROOT/$KIND"

# Managed services hide pg_authid, so this is best effort and without passwords.
log "[$KIND] Dumping roles"
pg pg_dumpall -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -l "$DB_MAINTENANCE_NAME" \
    --globals-only --no-role-passwords > "$WORK/db/globals.sql" 2>/dev/null \
    || log "[$KIND] WARNING: roles dump failed (not critical)"

log "[$KIND] Listing databases"
mapfile -t DBS < <(pg psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_MAINTENANCE_NAME" -Atc \
    "SELECT datname FROM pg_database WHERE datistemplate = false AND datname NOT IN ('postgres', '$DB_MAINTENANCE_NAME') ORDER BY datname")
log "[$KIND] ${#DBS[@]} database(s): ${DBS[*]}"
[[ ${#DBS[@]} -gt 0 ]] || { log "ERROR: no databases found"; exit 1; }

for db in "${DBS[@]}"; do
    pg pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -Fc --no-owner --no-privileges "$db" > "$WORK/db/${db}.dump"
done
printf '%s\n' "${DBS[@]}" > "$WORK/db/DATABASES.txt"
cat "$APP_DIR/.last_good_tag" > "$WORK/IMAGE_TAG.txt" 2>/dev/null || echo unknown > "$WORK/IMAGE_TAG.txt"

OUT="$BACKUP_ROOT/$KIND/$NAME.tar.gz"
tar -czf "$OUT" -C "$WORK" .
( cd "$BACKUP_ROOT/$KIND" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256" )
chmod 600 "$OUT" "$OUT.sha256"
log "[$KIND] Wrote $OUT ($(du -h "$OUT" | cut -f1))"

# The Sunday daily backup is also kept as the weekly copy.
if [[ "$KIND" == "daily" && "$(date +%u)" == "7" ]]; then
    mkdir -p "$BACKUP_ROOT/weekly"
    cp "$OUT" "$OUT.sha256" "$BACKUP_ROOT/weekly/"
    log "[$KIND] Copied to weekly/"
fi

# Retention
prune_keep() {  # prune_keep <dir> <count>: keep the newest <count> archives
    local dir="$1" keep="$2" file
    while read -r file; do
        rm -f "$file" "$file.sha256"
    done < <(find "$dir" -maxdepth 1 -name 'backup-*.tar.gz' -printf '%T@ %p\n' 2>/dev/null | sort -rn | tail -n +"$((keep + 1))" | cut -d' ' -f2-)
}
find "$BACKUP_ROOT/daily" -name 'backup-daily-*' -mtime +"$RETENTION_DAYS" -delete 2>/dev/null || true
prune_keep "$BACKUP_ROOT/weekly" "$WEEKLY_KEEP"
prune_keep "$BACKUP_ROOT/predeploy" "$PREDEPLOY_KEEP"

if [[ -n "$REMOTE" && "${BACKUP_SKIP_REMOTE:-0}" != "1" ]]; then
    log "[$KIND] Uploading to $REMOTE"
    rclone copy "$OUT" "$REMOTE/$KIND/"
    rclone copy "$OUT.sha256" "$REMOTE/$KIND/"
    rclone delete "$REMOTE/daily/" --min-age 30d 2>/dev/null || true
fi

if [[ -n "${BACKUP_PING_URL:-}" && "$KIND" == "daily" ]]; then
    curl -fsS -m 10 --retry 3 "$BACKUP_PING_URL" >/dev/null || true
fi

log "[$KIND] Done. Local usage: $(du -sh "$BACKUP_ROOT" | cut -f1)"
