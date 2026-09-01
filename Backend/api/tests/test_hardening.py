"""Production hardening: error responses, rate limiting, health probes, evidence URL signing.

These cover the seams that only misbehave in production - an HTML error page reaching a JSON
client, a rate limit that counts but never blocks, a health probe that reports OK while the
database is down, a stored URL that is itself a credential.
"""

import base64

import pytest
from django.core.cache import cache
from django.test import override_settings
from urllib.parse import parse_qs, urlparse

from api.services import blob_storage

# A syntactically valid connection string with a fake key. AccountKey has to be real base64 or
# the SDK refuses to parse it; nothing here ever reaches the network.
FAKE_KEY = base64.b64encode(b'not-a-real-account-key-just-for-tests').decode()
FAKE_CONNECTION = (
    'DefaultEndpointsProtocol=https;AccountName=teststorage;'
    'AccountKey=%s;EndpointSuffix=core.windows.net' % FAKE_KEY
)


@pytest.fixture
def azure_configured():
    """Point blob_storage at a fake account, and reset its cached client around the test."""
    blob_storage._service_client = None
    with override_settings(
        AZURE_STORAGE_CONNECTION_STRING=FAKE_CONNECTION,
        AZURE_STORAGE_CONTAINER_EVIDENCE='evidence',
        DEBUG=False,
    ):
        yield
    blob_storage._service_client = None


class TestExceptionHandler:
    """An unhandled exception must reach the client as JSON, and must not leak its detail."""

    def test_an_unexpected_error_returns_json_not_html(self, ta_user, client_for, monkeypatch):
        from api.views import batches as batches_views

        def boom(*args, **kwargs):
            raise RuntimeError(
                'connection failed: postgresql://admin:SUPERSECRET@db.internal:5432/prod'
            )

        monkeypatch.setattr(batches_views, 'visible_batches_qs', boom)

        response = client_for(ta_user).get('/api/batches/')

        assert response.status_code == 500
        assert response['Content-Type'].startswith('application/json')
        assert 'detail' in response.json()

    def test_the_exception_detail_is_not_returned_to_the_client(
        self, ta_user, client_for, monkeypatch
    ):
        """Exception messages carry connection strings, SQL with candidate PII, and provider
        responses that echo API keys. The detail belongs in the log, not the response.
        """
        from api.views import batches as batches_views

        def boom(*args, **kwargs):
            raise RuntimeError('postgresql://admin:SUPERSECRET@db.internal:5432/prod')

        monkeypatch.setattr(batches_views, 'visible_batches_qs', boom)

        body = client_for(ta_user).get('/api/batches/').content.decode()

        assert 'SUPERSECRET' not in body
        assert 'db.internal' not in body
        assert 'RuntimeError' not in body

    def test_a_normal_404_is_still_a_clean_json_404(self, ta_user, client_for):
        response = client_for(ta_user).get('/api/batches/999999/')
        assert response.status_code == 404
        assert response['Content-Type'].startswith('application/json')

    def test_an_unauthenticated_request_is_401_not_500(self, api_client):
        response = api_client.get('/api/batches/')
        assert response.status_code == 401


class TestRateLimiting:
    """The decorators use block=False, which only sets request.limited - the view has to check
    it. If a view ever forgets, the limit silently does nothing, so this asserts on real 429s.
    """

    def test_the_login_endpoint_starts_returning_429(self, api_client):
        payload = {'email': 'nobody@accelirate.com', 'password': 'wrong-password'}
        statuses = [api_client.post('/api/auth/login/', payload).status_code
                    for _ in range(14)]

        assert 429 in statuses, statuses
        # And it is the later ones that are limited, not everything from the start.
        assert statuses[0] != 429

    def test_the_limit_is_per_ip(self, api_client):
        payload = {'email': 'nobody@accelirate.com', 'password': 'wrong-password'}
        for _ in range(14):
            api_client.post('/api/auth/login/', payload, REMOTE_ADDR='10.0.0.1')

        # A different address must not inherit the first one's exhausted budget.
        response = api_client.post('/api/auth/login/', payload, REMOTE_ADDR='10.0.0.2')
        assert response.status_code != 429

    def test_clearing_the_cache_resets_the_counter(self, api_client):
        """Confirms the counters live in the cache - which is why a per-process cache in a
        multi-worker deployment makes every limit weaker (see api/checks.py, api.W001).
        """
        payload = {'email': 'nobody@accelirate.com', 'password': 'wrong-password'}
        for _ in range(14):
            api_client.post('/api/auth/login/', payload)
        cache.clear()
        assert api_client.post('/api/auth/login/', payload).status_code != 429


class TestHealthProbes:
    def test_liveness_needs_no_authentication(self, api_client):
        response = api_client.get('/api/health/')
        assert response.status_code == 200
        assert response.json()['status'] == 'ok'

    def test_liveness_reveals_nothing_about_the_deployment(self, api_client):
        """It is unauthenticated, so it must not be a reconnaissance endpoint."""
        body = api_client.get('/api/health/').json()
        assert set(body) == {'status', 'timestamp'}

    def test_readiness_reports_ready_when_the_database_answers(self, api_client, db):
        response = api_client.get('/api/health/ready/')
        assert response.status_code == 200
        assert response.json()['status'] == 'ready'

    def test_readiness_fails_when_the_database_does_not_answer(self, api_client, db,
                                                               monkeypatch):
        """The failure mode of the previous always-ok endpoint: a broken instance staying in the
        load balancer's rotation.
        """
        from api.views import health as health_views

        class BrokenConnection:
            def cursor(self):
                raise RuntimeError('could not connect to server')

        monkeypatch.setattr(health_views, 'connection', BrokenConnection())

        response = api_client.get('/api/health/ready/')
        assert response.status_code == 503
        assert response.json()['status'] == 'unavailable'

    def test_readiness_does_not_leak_the_database_error(self, api_client, db, monkeypatch):
        from api.views import health as health_views

        class BrokenConnection:
            def cursor(self):
                raise RuntimeError('FATAL: password authentication failed for user "talentgate"')

        monkeypatch.setattr(health_views, 'connection', BrokenConnection())

        body = api_client.get('/api/health/ready/').content.decode()
        assert 'password' not in body
        assert 'talentgate' not in body


class TestEvidenceUrlSigning:
    """Stored evidence URLs are unsigned pointers; a short-lived token is minted on read."""

    def test_nothing_in_nothing_out(self):
        assert blob_storage.fresh_read_url(None) is None
        assert blob_storage.fresh_read_url('') is None

    def test_an_unsigned_url_comes_back_signed(self, azure_configured):
        stored = 'https://teststorage.blob.core.windows.net/evidence/attempts/7/face_photo.jpg'
        signed = blob_storage.fresh_read_url(stored)

        query = parse_qs(urlparse(signed).query)
        assert 'sig' in query
        assert urlparse(signed).path == urlparse(stored).path

    def test_the_token_is_read_only(self, azure_configured):
        stored = 'https://teststorage.blob.core.windows.net/evidence/attempts/7/face_photo.jpg'
        query = parse_qs(urlparse(blob_storage.fresh_read_url(stored)).query)
        assert query['sp'] == ['r']

    def test_a_stale_token_is_replaced_not_appended(self, azure_configured):
        """Rows written under the old scheme carry a 365-day token. Re-signing must discard it,
        not produce a URL with two sets of SAS parameters.
        """
        stored = (
            'https://teststorage.blob.core.windows.net/evidence/attempts/7/face_photo.jpg'
            '?sv=2020-01-01&sig=OLDTOKEN%3D&se=2030-01-01T00%3A00%3A00Z&sp=r'
        )
        query = parse_qs(urlparse(blob_storage.fresh_read_url(stored)).query)

        assert len(query['sig']) == 1
        assert 'OLDTOKEN' not in query['sig'][0]
        assert not query['se'][0].startswith('2030')

    def test_a_url_for_another_account_is_passed_through_untouched(self, azure_configured):
        """A stale local-media URL from development must not get a token for the wrong account
        stapled onto it.
        """
        foreign = 'http://127.0.0.1:8000/media/exam_evidence/attempts/7/face_photo.jpg'
        assert blob_storage.fresh_read_url(foreign) == foreign

    def test_signing_never_raises(self, azure_configured):
        """An evidence link that does not work is bad; a 500 on the candidate detail page -
        which shows far more than evidence - is worse.
        """
        assert blob_storage.fresh_read_url('not even a url') == 'not even a url'
        assert blob_storage.fresh_read_url(
            'https://teststorage.blob.core.windows.net/') is not None

    def test_stored_urls_carry_no_credential(self, azure_configured):
        """The property that makes key rotation survivable and a leaked row harmless."""
        stored = 'https://teststorage.blob.core.windows.net/evidence/attempts/7/face_photo.jpg'
        assert 'sig=' not in stored
        assert '?' not in stored

    def test_with_no_azure_configured_urls_pass_through(self):
        """The local-disk fallback path - nothing to sign."""
        with override_settings(AZURE_STORAGE_CONNECTION_STRING='', DEBUG=True):
            url = 'http://127.0.0.1:8000/media/exam_evidence/attempts/7/face_photo.jpg'
            assert blob_storage.fresh_read_url(url) == url

    def test_download_filename_forces_an_attachment_disposition(self, azure_configured):
        """The plain HTML `download` attribute does nothing for a cross-origin blob URL - every
        major browser ignores it. Content-Disposition baked into the SAS token itself is what
        actually makes the browser save the file instead of navigating to it.
        """
        stored = 'https://teststorage.blob.core.windows.net/evidence/attempts/7/face_photo.jpg'
        signed = blob_storage.fresh_read_url(stored, download_filename='Asha_Rao_face_photo.jpg')

        query = parse_qs(urlparse(signed).query)
        assert query['rscd'] == ['attachment; filename="Asha_Rao_face_photo.jpg"']

    def test_no_download_filename_means_no_disposition_override(self, azure_configured):
        """The "view inline" case - no override, so the browser opens it in place."""
        stored = 'https://teststorage.blob.core.windows.net/evidence/attempts/7/face_photo.jpg'
        query = parse_qs(urlparse(blob_storage.fresh_read_url(stored)).query)
        assert 'rscd' not in query


class TestDeploymentChecks:
    """The api.W00x checks in api/checks.py, which surface misconfigurations Django's own
    checks know nothing about.
    """

    def test_per_process_cache_is_flagged_in_production(self):
        from api.checks import check_shared_cache_configured

        with override_settings(DEBUG=False, CACHES={'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }}):
            assert [w.id for w in check_shared_cache_configured(None)] == ['api.W001']

    def test_a_shared_cache_is_not_flagged(self):
        from api.checks import check_shared_cache_configured

        with override_settings(DEBUG=False, CACHES={'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': 'redis://localhost:6379/0',
        }}):
            assert check_shared_cache_configured(None) == []

    def test_nothing_is_flagged_in_local_development(self):
        from api.checks import check_shared_cache_configured
        with override_settings(DEBUG=True):
            assert check_shared_cache_configured(None) == []

    def test_missing_evidence_storage_is_flagged(self):
        from api.checks import check_evidence_storage_configured
        with override_settings(DEBUG=False, AZURE_STORAGE_CONNECTION_STRING=''):
            assert [w.id for w in check_evidence_storage_configured(None)] == ['api.W002']

    def test_a_public_webmail_domain_is_flagged(self):
        from api.checks import check_corporate_domains_not_public
        with override_settings(DEBUG=False,
                               CORPORATE_EMAIL_DOMAINS=['accelirate.com', 'gmail.com']):
            assert [w.id for w in check_corporate_domains_not_public(None)] == ['api.W004']

    def test_the_corporate_domain_alone_is_fine(self):
        from api.checks import check_corporate_domains_not_public
        with override_settings(DEBUG=False, CORPORATE_EMAIL_DOMAINS=['accelirate.com']):
            assert check_corporate_domains_not_public(None) == []


class TestAdminIsNotReachable:
    def test_the_django_admin_is_not_routed(self, api_client):
        """It registered every model with no write protection, against a different user table
        than the app authenticates with - an editable AuditLog and a readable
        Question.correct_option, on a login path with no rate limiting or lockout.

        This deliberately does not assert a 404 any more. The SPA catch-all in config/urls.py owns
        every non-/api path, and the React app has its own /admin/* screens (User Management,
        Question Bank, Audit Logs), so what /admin/ returns now depends on whether a frontend
        build is present - which differs between a developer's checkout and the backend CI job.
        The property worth pinning is that nothing under /admin/ is Django's admin, whichever of
        those two it is.
        """
        from django.urls import NoReverseMatch, reverse

        with pytest.raises(NoReverseMatch):
            reverse('admin:index')

        for path in ('/admin/', '/admin/login/'):
            body = api_client.get(path).content
            assert b'Django administration' not in body
            assert b'id="login-form"' not in body

    def test_the_admin_app_is_not_installed(self):
        from django.conf import settings
        assert 'django.contrib.admin' not in settings.INSTALLED_APPS


class TestPublicAuthEndpointsIgnoreAStaleAuthorizationHeader:
    """Reported: the staff login page showed SimpleJWT's raw "Given token not valid for any
    token type" instead of /auth/refresh/'s own "Session expired..." message.

    Root cause: none of these views override authentication_classes, so the global
    CustomJWTAuthentication (DEFAULT_AUTHENTICATION_CLASSES) still ran against whatever stale
    Authorization header the browser attached - axiosClient's interceptor attaches one to every
    request, including these - and rejected the request in DRF's authentication phase, before
    the view's own post() ever ran. permission_classes=[AllowAny] does not prevent this;
    authentication and permission are separate phases. A garbage/expired Bearer token must not
    stop any of these from running their own logic.
    """

    STALE_AUTH = {'HTTP_AUTHORIZATION': 'Bearer garbage-stale-access-token'}

    def test_refresh_runs_its_own_logic_not_a_stale_token_401(self, api_client):
        response = api_client.post('/api/auth/refresh/', **self.STALE_AUTH)
        # RefreshView's own check (no cookie present), not SimpleJWT's raw token error.
        assert response.data == {'detail': 'No refresh token.'}

    def test_login_runs_its_own_logic_not_a_stale_token_401(self, api_client, db):
        response = api_client.post(
            '/api/auth/login/', {'email': 'nobody@accelirate.com', 'password': 'wrong'},
            **self.STALE_AUTH,
        )
        assert response.data == {'detail': 'Invalid email or password.'}

    def test_forgot_password_runs_its_own_logic_not_a_stale_token_401(self, api_client, db):
        response = api_client.post(
            '/api/auth/forgot-password/', {'email': 'nobody@accelirate.com'}, **self.STALE_AUTH,
        )
        assert response.status_code == 400
        assert response.data['detail'] == 'No account found for this email address.'

    def test_resend_otp_runs_its_own_logic_not_a_stale_token_401(self, api_client, db):
        response = api_client.post(
            '/api/auth/resend-otp/', {'email': 'nobody@accelirate.com'}, **self.STALE_AUTH,
        )
        assert response.status_code == 200

    def test_verify_otp_reset_runs_its_own_logic_not_a_stale_token_401(self, api_client, db):
        response = api_client.post(
            '/api/auth/verify-otp/',
            {'email': 'nobody@accelirate.com', 'otp': '000000',
             'new_password': 'Whatever1Valid!', 'confirm_password': 'Whatever1Valid!'},
            **self.STALE_AUTH,
        )
        assert response.data == {'detail': 'Invalid or expired code.'}
