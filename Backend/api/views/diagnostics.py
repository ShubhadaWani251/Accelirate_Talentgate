"""Runtime facts about this deployment that only the running application can see.

This exists because of a specific gap, not as a general metrics surface. Several questions about
why the app is slow or unavailable can only be answered from inside a running instance - which
cache backend is actually live, how many database connections the role is holding against its
limit, whether a candidate's recording is as long as their exam was - and the people who need
those answers do not necessarily have Azure portal access. Without this, diagnosing a production
problem meant requesting permissions first and measuring afterwards.

Admin-only, read-only, and deliberately narrow:

  * Nothing here returns a secret. Not the database password, not the connection string, not
    REDIS_URL's value - only the CLASS NAME of the configured cache backend, which is the part
    that actually answers "are rate limits shared between instances or not".
  * Every number is read live. Nothing is hardcoded from documentation, because the point is to
    find out where documentation and reality have diverged.
  * It reports which instance answered. The deployment runs several behind a load balancer, so
    "the connection count" is per-instance and a single reading is a sample, not a total -
    calling this repeatedly and seeing different instance ids is how you cover all of them.
"""
import os
import time

from django.conf import settings
from django.db import connection
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import ExamAttempt
from api.permissions import IsAdmin

# Identifies the worker process that answered, so repeated calls can be told apart across
# instances. Not a hostname (which would be the same for every worker on one instance) and not
# anything that identifies the machine beyond this process.
_BOOT_ID = f'{os.getpid()}-{int(time.time())}'

# Cache backends that are genuinely shared between worker processes. LocMemCache is not: each
# process keeps its own, so every rate limit is silently multiplied by the number of processes
# and a login lockout can be stepped around by landing on a different one.
_SHARED_CACHE_MARKERS = ('redis', 'memcached', 'db.DatabaseCache', 'pymemcache', 'db.')


class DiagnosticsView(APIView):
    """GET /api/diagnostics/ - runtime state of the instance that answers.

    Optional `attempt=<id>` additionally reports whether that attempt's recording is as long as
    its exam was, which is how a silently dropped chunk shows up. Omitted by default because it
    costs a storage round trip.
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        payload = {
            'instance': {
                'boot_id': _BOOT_ID,
                'debug': settings.DEBUG,
                # The two gunicorn numbers that decide how many requests this instance can serve
                # at once, which is what everything else is measured against.
                'web_concurrency': os.environ.get('WEB_CONCURRENCY', '(default)'),
                'web_threads': os.environ.get('WEB_THREADS', '(default)'),
            },
            'cache': self._cache(),
            'database': self._database(),
        }
        attempt_id = request.query_params.get('attempt', '').strip()
        if attempt_id.isdigit():
            payload['recording'] = self._recording(int(attempt_id))
        return Response(payload)

    @staticmethod
    def _cache():
        """Which cache backend is live, and whether it is shared across processes.

        The value of REDIS_URL is never returned - it can carry credentials. `configured` says
        only whether it is set at all, which is the part worth knowing.
        """
        backend = (settings.CACHES or {}).get('default', {}).get(
            'BACKEND', 'django.core.cache.backends.locmem.LocMemCache')
        shared = any(marker in backend for marker in _SHARED_CACHE_MARKERS)
        return {
            'backend': backend,
            'shared_across_processes': shared,
            'redis_url_configured': bool(getattr(settings, 'REDIS_URL', '')),
            'note': (
                'Rate limits and the login lockout count here. A per-process cache means every '
                'published limit is effectively multiplied by the number of worker processes.'
            ) if not shared else None,
        }

    @staticmethod
    def _database():
        """Connection usage for this role against its own limit, read from Postgres itself.

        rolconnlimit is the per-role cap and max_connections the server-wide one; -1 means no
        role-specific limit, in which case the server total is the only ceiling. Both are read
        rather than taken from the README, because a mismatch between the two is exactly the
        kind of thing worth finding.
        """
        info = {'vendor': connection.vendor}
        if connection.vendor != 'postgresql':
            info['note'] = 'Connection accounting is PostgreSQL-only.'
            return info
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    (SELECT count(*) FROM pg_stat_activity
                      WHERE usename = current_user)                      AS role_connections,
                    (SELECT count(*) FROM pg_stat_activity
                      WHERE usename = current_user AND state = 'idle')   AS role_idle,
                    (SELECT count(*) FROM pg_stat_activity)              AS server_connections,
                    (SELECT rolconnlimit FROM pg_roles
                      WHERE rolname = current_user)                      AS role_limit,
                    current_setting('max_connections')::int              AS max_connections,
                    current_user                                         AS role_name
            """)
            row = dict(zip([c[0] for c in cursor.description], cursor.fetchone()))
        info.update(row)
        limit = row['role_limit']
        if limit and limit > 0:
            info['role_headroom'] = limit - row['role_connections']
            # The failure this is here to catch does not degrade - Postgres refuses the
            # connection outright with "too many connections for role", so the interesting
            # reading is how close it gets, not whether it has already happened.
            info['role_pct_used'] = round(row['role_connections'] / limit * 100, 1)
        return info

    @staticmethod
    def _recording(attempt_id):
        """Is this attempt's recording as long as its exam was?

        A chunk refused by the server - for exceeding DATA_UPLOAD_MAX_MEMORY_SIZE, say - is
        dropped by the browser without the candidate or anyone else being told, so a recording
        can arrive with holes in it and look perfectly normal. Comparing stored bytes against
        elapsed exam time is what makes that visible.

        Bytes are deliberately NOT converted into an expected duration: the encoder's real
        bitrate varies with how much is moving in frame, so a ratio would be a guess dressed up
        as a measurement. The raw numbers are given instead, for a human to judge.
        """
        from api.services import blob_storage

        attempt = (ExamAttempt.objects.filter(pk=attempt_id)
                   .select_related('invitation__batch').first())
        if attempt is None:
            return {'attempt_id': attempt_id, 'found': False}

        out = {
            'attempt_id': attempt_id,
            'found': True,
            'status': attempt.status,
            'has_recording_url': bool(attempt.session_recording_url),
            'exam_duration_minutes': getattr(
                attempt.invitation.batch, 'exam_duration_minutes', None),
        }
        if attempt.started_at and attempt.submitted_at:
            out['elapsed_seconds'] = int(
                (attempt.submitted_at - attempt.started_at).total_seconds())
        try:
            out['recording_bytes'] = blob_storage.recording_size(attempt_id)
        except Exception as exc:  # noqa: BLE001 - a diagnostic must not 500 on its own lookup
            out['recording_bytes'] = None
            out['recording_error'] = f'{type(exc).__name__}: {exc}'
        return out
