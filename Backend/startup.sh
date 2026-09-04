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

echo "==> Starting scheduled jobs"
# The four commands from README's "Scheduled jobs" section have to run on a timer, and this
# platform provides nothing to run them with: App Service on Linux has no cron, and WebJobs are
# Windows-only. Without process_email_queue in particular, invitation emails are never sent at
# all - creating an Invitation only queues it - and the failure is silent, because the UI
# correctly reports the invite as issued. That is the specific reason these live here.
#
# Deliberately NOT mirrored into docker-entrypoint.sh: the Docker stack runs the same commands
# in its own `scheduler` service (docker-compose.yml), which is the better shape wherever a
# second process is possible. Prefer a real scheduler over this loop if the hosting ever allows
# one - a Container Apps job or an external trigger survives the web container restarting.
#
# Each job runs its command and only THEN sleeps, so a run lasting longer than its interval
# delays the next tick rather than overlapping it. That matters for process_email_queue, which
# paces sends by INVITE_SEND_DELAY_SECONDS and can outlast a minute on a large batch; two
# concurrent runs could send the same invitation twice.
schedule() {
    interval=$1
    shift
    while true; do
        # stdout is dropped because process_email_queue reports on every quiet tick and would
        # bury the application log. Real sends are recorded through Django logging, and stderr
        # stays attached so a traceback still reaches the App Service log stream.
        python manage.py "$@" >/dev/null || echo "scheduler: '$*' exited $?" >&2
        sleep "$interval"
    done
}

# Backgrounded before the exec below, so gunicorn still replaces this shell as PID 1 and keeps
# receiving SIGTERM directly. These loops are killed with the container; an interrupted send
# leaves its row QUEUED, which the next run picks up - the queue exists for exactly that.
schedule 60 process_email_queue &
schedule 600 finalize_expired_attempts &
# 30s, not 60s like the others: this is what notices a closed browser/SEB process, and the
# whole point is catching that soon after it happens rather than only at the next full minute.
schedule 30 terminate_stale_attempts &
# No candidate is waiting on this one in real time (unlike process_email_queue) - a 10-minute
# cadence just bounds how long after an exam ends before its MP4 copy is ready.
schedule 600 transcode_recordings &

echo "==> Starting gunicorn"
# --config picks up gunicorn.conf.py, which binds to $PORT. App Service sets PORT and expects the
# app to listen on it; hardcoding 8000 here would make the container fail its health probe.
exec gunicorn --config gunicorn.conf.py config.wsgi:application
