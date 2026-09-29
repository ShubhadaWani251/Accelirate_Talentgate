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

echo "==> Installing rapidocr-onnxruntime (--no-deps)"
# Oryx's own `pip install -r requirements.txt` (which runs before this script, during deployment)
# never installs rapidocr-onnxruntime - it is deliberately absent from requirements.txt, because
# its metadata hard-depends on `opencv-python` (the GUI build), which pip would otherwise install
# alongside opencv-python-headless, corrupting the shared cv2/ install with a build that needs
# libGL.so.1 - a library this App Service Linux runtime does not have and has no apt-get access to
# install. cv2 is imported at module scope in services/aadhaar.py (for QR decoding), so that
# ImportError previously crashed the entire app at Django startup, not just Aadhaar-related
# requests - see requirements.in's comment for the full incident. --no-deps here installs
# rapidocr's own code only, with every other real dependency it needs already satisfied by
# requirements.txt. Guarded so a plain restart (not a fresh deploy) never re-hits PyPI - the
# package is already present in the persisted venv from the last deploy that ran this.
#
# Deliberately NOT fatal, unlike every other step here. rapidocr is imported lazily, inside
# services/aadhaar._get_ocr_engine(), so the app boots and serves perfectly well without it -
# only the OCR fallback degrades, leaving captures PENDING for a TA to review, which is a path
# the product already has. Under `set -e` a failure here would instead end this script and take
# the whole site down, meaning an unreachable PyPI - a third party we do not control, on a
# machine that only needs it on a fresh deploy - could stop candidates sitting an exam. --retries
# bounds how long that reachability test can cost us against App Service's 230s start limit.
python -c "import rapidocr_onnxruntime" 2>/dev/null \
    || pip install --no-deps --retries 2 rapidocr-onnxruntime==1.2.3 \
    || echo "startup: rapidocr install failed - Aadhaar OCR fallback is degraded, app continues" >&2

echo "==> Applying database migrations"
# At runtime, not build time: migrations need the real database, which only exists here. On a
# scaled-out plan several instances may start at once; Django locks per migration, so the losers
# no-op rather than double-apply.
#
# Retried, because of what `set -e` above turns a single failure into. This line is the only
# thing standing between the container and `exec gunicorn`, so one refused connection ends the
# script, no process ever listens on $PORT, and the site stays down until a human redeploys it.
# A database that is briefly unreachable - a failover, a maintenance restart, a network blip -
# is a condition that fixes itself in seconds; without a retry it costs an outage lasting until
# somebody notices. That asymmetry is the whole reason this loop exists.
#
# The budget is bounded on purpose. App Service kills a container that has not started listening
# within WEBSITES_CONTAINER_START_TIME_LIMIT (230s by default, and raising it needs portal
# access nobody here may have). Each attempt is capped by DB_CONNECT_TIMEOUT - 10s, set in
# settings.py DATABASES, which is what makes this loop bounded at all - plus ~3s of Django
# startup, so five attempts and four waits is ~85s worst case, leaving collectstatic and
# gunicorn's own boot inside the limit. Raise these only together with that platform setting;
# a retry loop that outlives the start limit is strictly worse than no retry, because the
# platform kills the container mid-wait and nothing completes.
#
# A migration that fails for a real reason - a bad migration, missing permissions, a schema
# conflict - still exhausts all five attempts and still exits non-zero, loudly. This buys time
# for a transient fault; it does not paper over a broken deploy, and it never starts the app
# against a schema the code does not expect.
migrate_attempts=${MIGRATE_MAX_ATTEMPTS:-5}
migrate_delay=${MIGRATE_RETRY_DELAY:-5}
migrate_attempt=1
while true; do
    # `if` rather than `&&`: a failure inside an if-condition does not trip `set -e`, which is
    # exactly the exemption this loop needs and nothing else here wants.
    if python manage.py migrate --noinput; then
        break
    fi
    if [ "$migrate_attempt" -ge "$migrate_attempts" ]; then
        echo "startup: migrate failed $migrate_attempts times, giving up" >&2
        exit 1
    fi
    echo "startup: migrate failed (attempt $migrate_attempt/$migrate_attempts), retrying in ${migrate_delay}s" >&2
    migrate_attempt=$((migrate_attempt + 1))
    sleep "$migrate_delay"
done

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
#
# The first argument is a one-off start delay, and it exists because of that same run-before-you-
# sleep ordering: every one of these used to fire simultaneously at container start. Each is a
# full Django process at ~127MB measured (the urlconf pulls cv2 and numpy in at module scope via
# services/aadhaar.py, and verify_aadhaar_ocr_fallback reaches ~179MB once RapidOCR loads), so
# seven at once is ~890MB of housekeeping landing in one burst - at the exact moment gunicorn is
# preloading that same app and forking its workers. On a 1.75GB plan that is most of the instance
# spent on background work during the one minute it can least afford it.
#
# Staggering costs nothing: these are backgrounded below, so sleeping here does not hold up the
# `exec gunicorn` at the end of this file. It only moves the work to after the app is already
# serving. The offsets also keep the three 600s jobs permanently out of phase - previously they
# started together and so stayed in lockstep forever, spiking in unison every ten minutes.
# Offsets drift as runtimes vary, so this makes collisions rare rather than impossible.
schedule() {
    delay=$1
    interval=$2
    shift 2
    sleep "$delay"
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
#
# Ordered by how much a late first run would actually cost a candidate, because the start delay
# is paid once per job and this ordering is the only thing deciding who waits for it. The
# arguments are `schedule <start delay> <interval> <command>`.
#
# 30s interval, and first off the line with no delay at all: this is what notices a closed
# browser/SEB process, so it is the one job here whose lateness somebody mid-exam would feel.
schedule 0 30 terminate_stale_attempts &
# Next, because a candidate is waiting on an invitation that nothing else in the system sends.
schedule 20 60 process_email_queue &
schedule 45 600 finalize_expired_attempts &
# No candidate is waiting on this one in real time (unlike process_email_queue) - a 10-minute
# cadence just bounds how long after an exam ends before its MP4 copy is ready. Held back
# further than the three above because it shells out to ffmpeg and is the heaviest job here.
schedule 90 600 transcode_recordings &
# Same 10-minute cadence as transcode_recordings - no candidate is waiting on this one in real
# time either. It is the deferred safety net for a capture whose inline OCR was skipped because
# no concurrency slot was free, so most ticks find nothing to do. Kept a clear 60s clear of
# transcode_recordings deliberately: those two are the heaviest jobs here and they share an
# interval, so the offset between them is the only thing stopping them spiking in unison on
# every single tick, the way they did when all seven started together.
schedule 150 600 verify_aadhaar_ocr_fallback &
# Daily. Deletes denylist rows for refresh tokens that have already expired on their own - the
# table otherwise grows one row per logout, forever. Nothing breaks if this lags, so it gets the
# longest interval here by a wide margin - and, for that same reason, the longest start delay.
schedule 210 86400 purge_expired_revoked_tokens &
# Daily, same reasoning as the line above. Deletes Aadhaar/face photos and session recordings
# once they pass EVIDENCE_RETENTION_DAYS (30 by default - see services/evidence_retention.py).
# The command and its service have existed since the retention policy was written but nothing
# ever ran them, so evidence accumulated indefinitely and the policy was on paper only. A day's
# granularity is ample against a 30-day window, and the sweep is idempotent.
schedule 270 86400 purge_expired_evidence &

echo "==> Starting gunicorn"
# --config picks up gunicorn.conf.py, which binds to $PORT. App Service sets PORT and expects the
# app to listen on it; hardcoding 8000 here would make the container fail its health probe.
exec gunicorn --config gunicorn.conf.py config.wsgi:application
