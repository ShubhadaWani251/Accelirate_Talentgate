"""The admin-only runtime diagnostics endpoint.

Most of these are about what the endpoint must NOT do. It exists to answer questions about a
running deployment without Azure access, which means it reads configuration and database state
and returns it over HTTP - so the risk it carries is leaking a credential, and that is what the
bulk of this file guards.
"""
import pytest

pytestmark = pytest.mark.django_db


class TestOnlyAdminsCanReachIt:
    """It reports internal state, so the permission is the first thing to get right."""

    def test_an_anonymous_caller_is_refused(self, api_client):
        assert api_client.get('/api/diagnostics/').status_code in (401, 403)

    def test_a_ta_is_refused(self, ta_user, client_for):
        """Deliberately IsAdmin rather than IsAdminOrTA. A TA has no use for connection counts,
        and this is the kind of endpoint whose audience should only ever grow on purpose.
        """
        assert client_for(ta_user).get('/api/diagnostics/').status_code == 403

    def test_an_admin_is_allowed(self, admin_user, client_for):
        assert client_for(admin_user).get('/api/diagnostics/').status_code == 200


class TestItLeaksNoSecrets:
    """The failure that would matter. Everything here is returned to a browser."""

    @pytest.fixture
    def body(self, admin_user, client_for, settings):
        settings.REDIS_URL = 'redis://:sup3rsecret@cache.internal:6379/0'
        import json
        return json.dumps(client_for(admin_user).get('/api/diagnostics/').json())

    def test_the_database_password_is_not_in_the_response(self, body, settings):
        password = settings.DATABASES['default'].get('PASSWORD') or ''
        if password:
            assert password not in body

    @pytest.mark.parametrize('secret_fragment', [
        'sup3rsecret',                 # the REDIS_URL credential set in the fixture above
        'redis://',                    # the whole URL, credential or not
        'AccountKey',                  # an Azure storage connection string
        'SECRET_KEY',
    ])
    def test_no_credential_shaped_value_appears(self, body, secret_fragment):
        assert secret_fragment not in body

    def test_it_reports_whether_redis_is_configured_without_revealing_it(
        self, admin_user, client_for, settings
    ):
        """The useful fact is "is a shared cache configured", which is a boolean. The URL itself
        carries a password and is never the answer to that question.
        """
        settings.REDIS_URL = 'redis://:sup3rsecret@cache.internal:6379/0'

        cache = client_for(admin_user).get('/api/diagnostics/').json()['cache']

        assert cache['redis_url_configured'] is True
        assert 'sup3rsecret' not in str(cache)


class TestTheCacheSection:
    """Answers "are rate limits shared between instances, or counted separately by each one"."""

    def test_it_names_the_live_backend(self, admin_user, client_for):
        cache = client_for(admin_user).get('/api/diagnostics/').json()['cache']

        assert 'LocMemCache' in cache['backend']

    def test_locmem_is_reported_as_not_shared(self, admin_user, client_for):
        """The suite runs on LocMemCache, which is the exact configuration this flag exists to
        catch in production - per-process, so every limit is multiplied by the worker count.
        """
        cache = client_for(admin_user).get('/api/diagnostics/').json()['cache']

        assert cache['shared_across_processes'] is False
        assert cache['note'], 'an unshared cache should explain what that costs'

    def test_a_shared_backend_is_reported_as_shared(self, admin_user, client_for, settings):
        settings.CACHES = {'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': 'redis://localhost:6379/0',
        }}

        cache = client_for(admin_user).get('/api/diagnostics/').json()['cache']

        assert cache['shared_across_processes'] is True
        assert cache['note'] is None


class TestTheDatabaseSection:
    def test_it_degrades_rather_than_failing_off_postgres(self, admin_user, client_for):
        """The suite runs on SQLite, where pg_stat_activity does not exist. A diagnostic that
        500s on the wrong engine is useless in exactly the situation someone reaches for it.
        """
        db = client_for(admin_user).get('/api/diagnostics/').json()['database']

        assert db['vendor'] == 'sqlite'
        assert 'note' in db


class TestTheRecordingSection:
    """Only present when asked for, because it costs a storage round trip."""

    def test_it_is_absent_unless_an_attempt_is_named(self, admin_user, client_for):
        assert 'recording' not in client_for(admin_user).get('/api/diagnostics/').json()

    def test_an_unknown_attempt_reports_not_found_rather_than_erroring(
        self, admin_user, client_for
    ):
        body = client_for(admin_user).get('/api/diagnostics/?attempt=999999').json()

        assert body['recording']['found'] is False

    def test_a_non_numeric_attempt_is_ignored(self, admin_user, client_for):
        """Straight into a model lookup, so it has to be rejected before it gets there."""
        response = client_for(admin_user).get('/api/diagnostics/?attempt=notanumber')

        assert response.status_code == 200
        assert 'recording' not in response.json()

    def test_a_storage_failure_is_reported_not_raised(
        self, admin_user, client_for, ta_user, make_batch, make_candidate, make_invitation,
        stocked_question_bank, monkeypatch,
    ):
        """Storage being unreachable is itself worth knowing, and is often WHY somebody opened
        this endpoint. It must not take the rest of the report down with it.
        """
        from api.services import blob_storage, exam_session

        invitation = make_invitation(make_candidate(make_batch(ta_user), ta_user), ta_user)
        attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')
        monkeypatch.setattr(blob_storage, 'recording_size',
                            lambda _id: (_ for _ in ()).throw(RuntimeError('storage unreachable')))

        body = client_for(admin_user).get(
            f'/api/diagnostics/?attempt={attempt.attempt_id}').json()

        assert body['recording']['found'] is True
        assert body['recording']['recording_bytes'] is None
        assert 'storage unreachable' in body['recording']['recording_error']
        assert 'cache' in body, 'one failing section must not remove the others'


class TestItSaysWhichInstanceAnswered:
    def test_a_boot_id_is_returned(self, admin_user, client_for):
        """The deployment runs several instances behind a load balancer, so any single reading
        is a sample of one of them. Without something to tell them apart, repeated calls cannot
        be told from repeated readings of the same instance.
        """
        body = client_for(admin_user).get('/api/diagnostics/').json()

        assert body['instance']['boot_id']
