"""Serves the built React SPA from the same origin as the API.

Same-origin is a requirement here, not a preference. The refresh token rides in an httpOnly
SameSite cookie (see REFRESH_COOKIE_SAMESITE in settings.py), and a genuinely cross-site
frontend/API pair makes the browser withhold that cookie on every refresh call, logging users
out mid-session with no error anywhere. Frontend/nginx.conf solves this for the Docker stack by
proxying /api/ alongside the static files; this module solves it for a single App Service, where
gunicorn is the only process listening and there is no nginx in front of it.

WhiteNoise (see WHITENOISE_ROOT) serves the fingerprinted bundles under /assets/ and the root
files like favicon.svg from its middleware, ahead of the URL resolver. Only genuine client-side
routes fall through to the view below.
"""
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


@require_safe
@never_cache
def index(request):
    """Return the SPA shell for any route the React router owns.

    never_cache because index.html references Vite's fingerprinted asset filenames, which
    change on every build: a browser holding a cached shell would request bundles that no
    longer exist. This mirrors the `Cache-Control: no-store` that nginx.conf sets on the
    same file.

    A missing build is a 404 rather than a 500 so that an API-only deployment - or a local
    checkout where Vite's dev server is serving the frontend on :5173 instead - still starts
    and serves /api/ normally.
    """
    index_file = Path(settings.FRONTEND_DIST) / 'index.html'
    if not index_file.is_file():
        raise Http404('No frontend build present in FRONTEND_DIST.')
    # Read into a buffered response rather than streaming it with FileResponse. The shell is a
    # few hundred bytes, so there is nothing to stream, and a plain HttpResponse keeps the body
    # readable by anything that inspects responses - middleware and tests alike.
    return HttpResponse(index_file.read_bytes(), content_type='text/html')
