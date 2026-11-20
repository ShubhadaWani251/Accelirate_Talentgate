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


class TestTheShellCarriesThisEnvironmentsConfig:
    """The frontend is built once and promoted to every environment, so anything compiled into
    the bundle is identical everywhere. Per-environment values therefore have to arrive with the
    page instead - see config/spa._runtime_config_tag.

    The failure this guards against is silent and late: production signing in as staging's Entra
    application, which looks fine until the token is rejected at the very end.
    """

    def _config_from(self, body):
        """The JSON the shell handed the browser, parsed back out of the script tag."""
        import json
        import re
        match = re.search(r'window\.__APP_CONFIG__=(\{.*?\});', body)
        assert match, f'no config tag in the shell: {body!r}'
        return json.loads(match.group(1).replace(r'<\/', '</'))

    @override_settings(SSO_ENABLED=True, SSO_CLIENT_ID='client-abc', SSO_TENANT_ID='tenant-xyz')
    def test_the_configured_registration_reaches_the_browser(self, client, built_frontend):
        config = self._config_from(client.get('/login').content.decode())
        assert config == {'ssoClientId': 'client-abc', 'ssoTenantId': 'tenant-xyz'}

    @override_settings(SSO_ENABLED=False, SSO_CLIENT_ID='client-abc', SSO_TENANT_ID='tenant-xyz')
    def test_switching_sso_off_blanks_it_rather_than_omitting_it(self, client, built_frontend):
        """Blank is what msal.isSsoConfigured() reads as "no registration", which hides the
        button and leaves the password form. Omitting the tag entirely would work too, but
        only by accident - this keeps the off state explicit.
        """
        config = self._config_from(client.get('/login').content.decode())
        assert config == {'ssoClientId': '', 'ssoTenantId': ''}

    @override_settings(SSO_ENABLED=True, SSO_CLIENT_ID='a</script><script>alert(1)</script>',
                       SSO_TENANT_ID='t')
    def test_a_value_cannot_break_out_of_its_script_tag(self, client, built_frontend):
        """These values come from settings rather than from a request, so this is defence in
        depth - but a config channel that can be closed by its own payload is one bad settings
        edit away from being an injection point.
        """
        body = client.get('/login').content.decode()
        assert '</script><script>alert(1)' not in body
        # Still round-trips to the exact value, escaping and all.
        assert self._config_from(body)['ssoClientId'] == 'a</script><script>alert(1)</script>'

    @override_settings(SSO_ENABLED=True, SSO_CLIENT_ID='c', SSO_TENANT_ID='t')
    def test_it_goes_in_the_head_when_there_is_one(self, client, tmp_path):
        (tmp_path / 'index.html').write_text(
            '<!doctype html><html><head><title>t</title></head><body></body></html>',
            encoding='utf-8',
        )
        with override_settings(FRONTEND_DIST=tmp_path):
            body = client.get('/login').content.decode()
        assert body.index('__APP_CONFIG__') < body.index('</head>')

    @override_settings(SSO_ENABLED=True, SSO_CLIENT_ID='c', SSO_TENANT_ID='t')
    def test_a_shell_with_no_head_still_gets_it(self, client, built_frontend):
        """The fixture above has no </head>, so the </body> fallback is what runs here. Both
        positions are parsed before the deferred module bundle, so either works.
        """
        body = client.get('/login').content.decode()
        assert body.index('__APP_CONFIG__') < body.index('</body>')

    @override_settings(SSO_ENABLED=True, SSO_CLIENT_ID='c', SSO_TENANT_ID='t')
    def test_an_unrecognisable_shell_is_served_intact(self, client, tmp_path):
        """Not something Vite produces. Serving it whole - with sign-in simply off - beats
        corrupting it, and beats prepending a script ahead of the doctype, which would drop the
        whole page into quirks mode.
        """
        original = '<!doctype html><html><div id="root"></div></html>'
        (tmp_path / 'index.html').write_text(original, encoding='utf-8')
        with override_settings(FRONTEND_DIST=tmp_path):
            response = client.get('/login')
        assert response.status_code == 200
        assert response.content.decode() == original
