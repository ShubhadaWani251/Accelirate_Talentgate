"""Release Postgres connections back to the server after every web request.

CONN_MAX_AGE alone does not solve this: Django only re-checks a persistent connection's age
when the *same worker thread* handles its next request, so an idle gunicorn worker can hold a
slot open indefinitely. That was observed live against the shared staging server (connections
idling for 47+ minutes) while max_connections on the Burstable tier is only ~50 and shared
with local dev machines too.

Closing here gives the load benefit of CONN_MAX_AGE during a request (multiple ORM queries
share one connection) without letting workers hoard slots between requests. Management commands
run in separate processes and already drop their connection on exit; this middleware targets
only the long-lived gunicorn workers.
"""

from django.db import connections


class ReleaseDbConnectionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        finally:
            connections.close_all()
