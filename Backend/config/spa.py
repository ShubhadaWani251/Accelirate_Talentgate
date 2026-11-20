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

This module also hands the browser the few settings it cannot be built with - see
_runtime_config_tag.
"""
import json
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

# Where the config tag is injected, in preference order. All three positions execute before the
# application bundle does: Vite emits it as <script type="module">, which is deferred, and a
# deferred script runs only once the whole document has been parsed. A plain inline script
# anywhere in the document therefore wins the race regardless of which of these is used.
#
# Never prepended ahead of the doctype, which is why there is no final "just put it first"
# fallback: a script before <!doctype html> drops the page into quirks mode, which would
# silently change how every stylesheet in the app renders.
_INJECTION_POINTS = (b'</head>', b'</body>')


def _runtime_config_tag():
    """The settings the browser needs before it can make its first request.

    WHY THIS EXISTS. Vite inlines import.meta.env at BUILD time, and this pipeline builds the
    frontend once and promotes that one artifact to every environment (azure-pipelines.yml).
    Anything baked into the bundle is therefore the SAME in staging and production, so a
    per-environment value cannot travel that way - an App Service application setting is a
    runtime variable and arrives long after the bundle that needed it was written. Setting
    VITE_SSO_CLIENT_ID on a web app does nothing at all, with no error to say so.

    Handing it over at page load instead keeps one artifact - production runs the exact bytes
    that were tested on staging - while each environment serves its own values.

    It also collapses two settings into one. The browser's client id and the server's audience
    check have to name the same Entra application; they used to be two values (VITE_SSO_CLIENT_ID
    at build, SSO_CLIENT_ID at runtime) that nothing compared. When they drifted the failure was
    silent and late: the Microsoft account picker worked, and the token was rejected afterwards.
    Now both read SSO_CLIENT_ID, so they cannot disagree.

    Blank when SSO is switched off, which is the same state as a deployment that was never given
    a registration: msal.isSsoConfigured() returns false, the login screen shows the password
    form alone, and nothing on it is half-wired.

    NOTE for anyone adding a Content-Security-Policy later: this is an inline script, so it will
    need a nonce or it will be blocked - and the symptom will be single sign-on quietly
    disappearing rather than an obvious error.
    """
    enabled = settings.SSO_ENABLED
    config = {
        'ssoClientId': settings.SSO_CLIENT_ID if enabled else '',
        'ssoTenantId': settings.SSO_TENANT_ID if enabled else '',
    }
    # Escaped so that a value can never close the tag it sits in. "</" cannot occur outside a
    # string in JSON, and "<\/" is the same string to a JavaScript parser, so this is safe to
    # apply to the whole payload rather than to each value.
    payload = json.dumps(config).replace('</', r'<\/')
    return f'<script>window.__APP_CONFIG__={payload};</script>'.encode('utf-8')


def _inject(html, tag):
    """Place `tag` in `html` at the first available injection point.

    Returns the document unchanged if none is found, rather than guessing. An index.html with
    neither a </head> nor a </body> is not something Vite produces, so reaching that branch
    means the shell is not the file this function was written for - and serving it intact, with
    single sign-on switched off, beats corrupting it.
    """
    for marker in _INJECTION_POINTS:
        if marker in html:
            return html.replace(marker, tag + marker, 1)
    return html


@require_safe
@never_cache
def index(request):
    """Return the SPA shell for any route the React router owns.

    never_cache because index.html references Vite's fingerprinted asset filenames, which
    change on every build: a browser holding a cached shell would request bundles that no
    longer exist. This mirrors the `Cache-Control: no-store` that nginx.conf sets on the
    same file. It is now doing a second job too - the shell carries this environment's
    configuration, so a cached copy would be a cached client id.

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
    html = _inject(index_file.read_bytes(), _runtime_config_tag())
    return HttpResponse(html, content_type='text/html')
