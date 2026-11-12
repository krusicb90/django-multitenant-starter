#!/usr/bin/env bash
# Deploy an image tag on the production host, or roll back.
#
#   deploy.sh <image-tag>     deploy that build
#   deploy.sh --rollback      redeploy the last tag that became healthy
#
# Steps: registry login -> pull -> pre-deploy database backup -> compose up
#        -> wait for the health check -> on failure roll back to the previous tag.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/app}"
cd "$APP_DIR"

LAST_GOOD_FILE="$APP_DIR/.last_good_tag"
WEB_CONTAINER=app-web
# The entrypoint migrates every tenant database before gunicorn starts.
WAIT_SECONDS="${WAIT_SECONDS:-420}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

[[ -f .env ]] || { log "ERROR: $APP_DIR/.env missing"; exit 1; }
set -a
# shellcheck source=/dev/null
source .env
set +a
: "${DOMAIN:?DOMAIN missing in .env}"

TARGET_TAG="${1:-}"
if [[ "$TARGET_TAG" == "--rollback" ]]; then
    [[ -f "$LAST_GOOD_FILE" ]] || { log "ERROR: no known-good tag recorded"; exit 1; }
    TARGET_TAG="$(cat "$LAST_GOOD_FILE")"
    log "Rolling back to $TARGET_TAG"
fi
[[ -n "$TARGET_TAG" ]] || { echo "Usage: deploy.sh <image-tag> | --rollback"; exit 1; }

PREVIOUS_TAG="$(cat "$LAST_GOOD_FILE" 2>/dev/null || true)"

set_tag() {
    if grep -q '^IMAGE_TAG=' .env; then
        sed -i "s|^IMAGE_TAG=.*|IMAGE_TAG=$1|" .env
    else
        echo "IMAGE_TAG=$1" >> .env
    fi
    export IMAGE_TAG="$1"
}

wait_healthy() {
    local deadline=$(( $(date +%s) + WAIT_SECONDS ))
    local status
    while (( $(date +%s) < deadline )); do
        status="$(docker inspect -f '{{.State.Health.Status}}' "$WEB_CONTAINER" 2>/dev/null || echo missing)"
        if [[ "$status" == "healthy" ]]; then
            # Also check the whole path: nginx, TLS and Django. -k because an
            # origin certificate is not signed by a public CA.
            if curl -fsSk -o /dev/null --resolve "${DOMAIN}:443:127.0.0.1" "https://${DOMAIN}/health/"; then
                return 0
            fi
        fi
        if [[ "$status" == "unhealthy" ]]; then
            log "web container reported unhealthy"
            return 1
        fi
        sleep 5
    done
    log "timed out after ${WAIT_SECONDS}s waiting for web to become healthy"
    return 1
}

log "Deploying tag: $TARGET_TAG (previous: ${PREVIOUS_TAG:-none})"

if [[ -n "${REGISTRY_USER:-}" && -n "${REGISTRY_TOKEN:-}" ]]; then
    echo "$REGISTRY_TOKEN" | docker login "${REGISTRY:-ghcr.io}" -u "$REGISTRY_USER" --password-stdin >/dev/null
fi

set_tag "$TARGET_TAG"
log "Pulling images"
docker compose pull --quiet web cron

# Safety net before migrations run. Skipped on the very first deploy and with
# SKIP_PREDEPLOY_BACKUP=1. The nightly cron job makes the full backups.
if [[ "${SKIP_PREDEPLOY_BACKUP:-0}" != "1" && -n "$PREVIOUS_TAG" ]]; then
    log "Pre-deploy database backup"
    BACKUP_KIND=predeploy BACKUP_SKIP_REMOTE=1 "$APP_DIR/backup.sh"
fi

docker compose up -d --remove-orphans

if wait_healthy; then
    echo "$TARGET_TAG" > "$LAST_GOOD_FILE"
    log "Deploy OK: $TARGET_TAG is live"
    docker image prune -af --filter "until=72h" >/dev/null 2>&1 || true
    docker compose ps
    exit 0
fi

log "Deploy FAILED. Recent web logs:"
docker logs --tail 80 "$WEB_CONTAINER" || true

if [[ -n "$PREVIOUS_TAG" && "$PREVIOUS_TAG" != "$TARGET_TAG" ]]; then
    log "Rolling back to $PREVIOUS_TAG"
    set_tag "$PREVIOUS_TAG"
    docker compose up -d --remove-orphans
    if wait_healthy; then
        log "Rollback OK: $PREVIOUS_TAG is live again"
    else
        log "Rollback did NOT become healthy. Manual intervention required."
    fi
fi
exit 1
