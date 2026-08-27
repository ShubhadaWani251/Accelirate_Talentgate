"""The SPA fallback that lets client-side routes survive a cold page load.

The assessment link in every invitation email is a bare /t/<token> URL. That path exists only in
the React router, so a candidate opening it from their inbox asks Django for it directly - and
without the catch-all in config/urls.py they get a 404 instead of their exam. It is the one route
in this app that is always entered by a cold load rather than client-side navigation, which is
why the fallback is worth pinning down here rather than trusting it by inspection.
"""

import pytest
from django.test import override_settings


@pytest.fixture
def built_frontend(tmp_path):
    """Stands in for Frontend/dist, which only exists after a Vite build.

    The backend suite runs in its own CI job with no Node toolchain, so the real build is never
    present when these tests execute. Faking the one file the view actually opens keeps this
    independent of the frontend pipeline instead of silently skipping whenever it hasn't run.
    """
    (tmp_path / 'index.html').write_text(
        '<!doctype html><html><body><div id="root"></div></body></html>',
        encoding='utf-8',
    )
    with override_settings(FRONTEND_DIST=tmp_path):
        yield tmp_path


@pytest.mark.parametrize('path', [
    '/',
    '/login',
    '/t/abc123token',
    '/batches/42',
    '/admin/question-bank',
])
def test_client_side_routes_return_the_shell(client, built_frontend, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response['Content-Type'] == 'text/html'


def test_shell_is_not_cached(client, built_frontend):
    # index.html names Vite's fingerprinted bundles, and those names change every build. A cached
    # shell therefore asks for assets that no longer exist after a deploy, which presents as a
    # blank page with no error - the same reason nginx.conf sets no-store on this file.
    response = client.get('/t/abc123token')
    assert 'no-store' in response['Cache-Control']


def test_unknown_api_paths_do_not_get_the_shell(client, built_frontend):
    # This is what the negative lookahead in the catch-all buys. Without it an unmatched /api/
    # path would return the HTML shell with a 200, so a mistyped endpoint would reach the client
    # as a JSON parse error somewhere in axios rather than an honest 404.
    response = client.get('/api/does-not-exist/')
    assert response.status_code == 404
    assert b'id="root"' not in response.content


def test_missing_build_is_a_404_not_a_500(client, tmp_path):
    # An API-only deployment - or a local checkout where Vite serves the frontend on :5173 - has
    # no build to hand back. That has to stay a 404 so the process still boots and serves /api/
    # normally instead of failing every request to it.
    with override_settings(FRONTEND_DIST=tmp_path / 'no-build-here'):
        response = client.get('/')
    assert response.status_code == 404


def test_shell_rejects_unsafe_methods(client, built_frontend):
    # require_safe on the view. The catch-all matches every non-/api path, so without it a stray
    # POST to a mistyped URL would be answered with 200 and the HTML shell.
    response = client.post('/login')
    assert response.status_code == 405
