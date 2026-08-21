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
python manage.py migrate --noinput

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
