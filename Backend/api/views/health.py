"""Liveness and readiness endpoints.

Both are unauthenticated on purpose - a load balancer or container runtime probing them has no
credentials - so neither may reveal anything about the deployment. That means no version string,
no hostname, no settings values, and no exception text: a probe that leaks the database error it
just hit is a reconnaissance endpoint.

The split matters. Liveness answers "is this process wedged, should it be restarted"; readiness
answers "should this instance receive traffic". Reporting healthy while the database is
unreachable keeps a broken instance in the load balancer's rotation, which is the failure mode
the previous single always-ok endpoint had.
"""

import logging

from django.db import connection
from django.http import JsonResponse
from django.utils import timezone

logger = logging.getLogger(__name__)


def health_check(request):
    """Liveness: the process is up and can serve a request. Deliberately touches nothing else.

    Kept dependency-free so a database blip doesn't cause the orchestrator to kill and restart
    otherwise-healthy containers - restarting an app server does not fix a database.
    """
    return JsonResponse({
        'status': 'ok',
        'timestamp': timezone.now().isoformat(),
    })


def readiness_check(request):
    """Readiness: this instance can actually serve real traffic, i.e. the database answers.

    SELECT 1 rather than an ORM query so it stays cheap enough to be polled every few seconds
    and doesn't depend on any particular table existing.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        # Logged in full (this is the one place the detail is useful) but never returned.
        logger.exception('Readiness check failed: database unreachable')
        return JsonResponse(
            {'status': 'unavailable', 'timestamp': timezone.now().isoformat()},
            status=503,
        )
    return JsonResponse({
        'status': 'ready',
        'timestamp': timezone.now().isoformat(),
    })
