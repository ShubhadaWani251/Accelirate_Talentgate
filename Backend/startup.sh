#!/bin/sh
# App Service (Linux, code deployment) startup command.
#
# This is the non-container counterpart to docker-entrypoint.sh, which App Service never invokes
# because it runs the app from a zip on its own Python image rather than from our Dockerfile.
# The two files deliberately do the same three things in the same order; if you change one,
# change the other.
#
# `exec` on the last line matters: it makes gunicorn PID 1 of this shell's process tree, so the
# SIGTERM App Service sends when recycling the instance reaches gunicorn itself and in-flight
# requests are drained instead of killed.
set -e

echo "==> Applying database migrations"
# At runtime, not build time: migrations need the real database, which only exists here. On a
# scaled-out plan several instances may start at once; Django locks per migration, so the losers
# no-op rather than double-apply.
python manage.py migrate --noinput

echo "==> Collecting static files"
# Django's own static assets (DRF's browsable-API CSS, and anything under Backend/static/) into
# STATIC_ROOT for WhiteNoise. This is separate from the React bundle, which the pipeline copies
# into FRONTEND_DIST and WhiteNoise serves from there - see config/spa.py.
python manage.py collectstatic --noinput --clear

echo "==> Running deployment checks (warnings are not fatal)"
# Surfaces the api.W00x checks in api/checks.py: shared cache, evidence storage, support address,
# corporate domain. Non-blocking on purpose - each is legitimate in some environment - but this
# puts them in the App Service log stream where they get seen.
python manage.py check --deploy || true

echo "==> Starting gunicorn"
# --config picks up gunicorn.conf.py, which binds to $PORT. App Service sets PORT and expects the
# app to listen on it; hardcoding 8000 here would make the container fail its health probe.
exec gunicorn --config gunicorn.conf.py config.wsgi:application
