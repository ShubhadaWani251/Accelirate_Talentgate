#!/bin/sh
# Container entrypoint: prepare the app, then hand off to whatever command was requested.
#
# `exec "$@"` at the end matters - it replaces this shell with the real process so that PID 1 is
# gunicorn itself. Without it, SIGTERM on deploy goes to the shell and gunicorn never gets the
# signal to shut down gracefully, so in-flight requests are killed rather than drained.
set -e

echo "==> Applying database migrations"
# Migrations run here rather than at image build time because they need the real database, which
# only exists at runtime. On a multi-instance rollout this means several containers may race;
# Django takes a lock per migration, so the losers no-op rather than double-apply.
#
# Retried for the reason startup.sh spells out in full: under `set -e` a single refused
# connection ends this script, the app is never exec'd, and a database that would have been back
# in seconds costs an outage lasting until a human intervenes. Here it also covers the ordinary
# compose case of this container winning the race against the `db` service's first boot.
# Each attempt is capped by DB_CONNECT_TIMEOUT (settings.py DATABASES), which is what keeps the
# loop bounded. Exhausting the attempts still exits non-zero, so a genuinely broken migration
# fails as loudly as it did before.
migrate_attempts=${MIGRATE_MAX_ATTEMPTS:-5}
migrate_delay=${MIGRATE_RETRY_DELAY:-5}
migrate_attempt=1
while true; do
    # `if` rather than `&&`: a failure inside an if-condition does not trip `set -e`.
    if python manage.py migrate --noinput; then
        break
    fi
    if [ "$migrate_attempt" -ge "$migrate_attempts" ]; then
        echo "entrypoint: migrate failed $migrate_attempts times, giving up" >&2
        exit 1
    fi
    echo "entrypoint: migrate failed (attempt $migrate_attempt/$migrate_attempts), retrying in ${migrate_delay}s" >&2
    migrate_attempt=$((migrate_attempt + 1))
    sleep "$migrate_delay"
done

echo "==> Collecting static files"
# Idempotent, and cheap when nothing changed. Kept at runtime rather than build time so that a
# STATIC_ROOT on a mounted volume is populated correctly.
python manage.py collectstatic --noinput --clear

echo "==> Running deployment checks (warnings are not fatal)"
# --deploy surfaces the api.W00x checks in api/checks.py: shared cache, evidence storage,
# support address, corporate domains. Deliberately does not block startup - each of those is
# legitimate in some environment - but it puts them in the deployment log where they get seen.
python manage.py check --deploy || true

echo "==> Starting: $*"
exec "$@"
