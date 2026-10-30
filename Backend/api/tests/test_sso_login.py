"""Signing in with a Microsoft work account.

Every token here is REAL: minted with an RSA key this module generates, signed RS256, and
verified through the same jwt.decode path production uses, with only the JWKS lookup replaced
so the tests do not reach Entra. Asserting against mocks would prove the view calls a
validator, not that the validator refuses a forged token - and refusing forged tokens is the
entire security value of this feature.
"""
import time
from datetime import timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.utils import timezone

from api.models import AuditLog
from api.services import sso

pytestmark = pytest.mark.django_db

TENANT = '11111111-2222-3333-4444-555555555555'
CLIENT_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
OTHER_TENANT = '99999999-9999-9999-9999-999999999999'


@pytest.fixture(scope='module')
def signing_key():
    """One keypair for the module - RSA generation is slow enough to matter per-test."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def sso_configured(settings, signing_key, monkeypatch):
    """Turn SSO on and point the JWKS lookup at our own key instead of Entra's."""
    settings.SSO_ENABLED = True
    settings.SSO_CLIENT_ID = CLIENT_ID
    settings.SSO_TENANT_ID = TENANT
    settings.CORPORATE_EMAIL_DOMAINS = ['accelirate.com']

    class _Key:
        key = signing_key.public_key()

    class _Jwks:
        def get_signing_key_from_jwt(self, token):
            return _Key()

    monkeypatch.setattr(sso, '_jwks', lambda: _Jwks())
    sso._reset_jwks_cache()
    yield
    sso._reset_jwks_cache()


def make_token(signing_key, **overrides):
    """A well-formed Entra ID token, with any claim overridable to break exactly one thing."""
    now = int(time.time())
    claims = {
        'iss': f'https://login.microsoftonline.com/{TENANT}/v2.0',
        'aud': CLIENT_ID,
        'tid': TENANT,
        'oid': '00000000-1111-2222-3333-444444444444',
        'preferred_username': 'staff@accelirate.com',
        'name': 'Staff Member',
        'iat': now,
        'nbf': now,
        'exp': now + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, signing_key, algorithm='RS256')


def post_sso(client, token):
    return client.post('/api/auth/sso/', {'id_token': token}, format='json')


class TestATokenMustBeGenuine:
    def test_a_valid_token_signs_an_existing_user_in(self, make_user, api_client, signing_key):
        make_user(email='staff@accelirate.com')

        response = post_sso(api_client, make_token(signing_key))

        assert response.status_code == 200
        assert response.data['access_token']
        assert response.data['user']['email'] == 'staff@accelirate.com'

    def test_a_token_signed_by_someone_else_is_refused(self, make_user, api_client):
        """The whole point: anyone can mint claims, only Entra can sign them."""
        make_user(email='staff@accelirate.com')
        attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        response = post_sso(api_client, make_token(attacker_key))

        assert response.status_code == 401

    def test_a_token_for_another_application_is_refused(self, make_user, api_client, signing_key):
        """A real Entra signature, but minted for a different app - aud is what catches it."""
        make_user(email='staff@accelirate.com')

        response = post_sso(api_client, make_token(signing_key, aud='some-other-app'))

        assert response.status_code == 401

    def test_a_token_from_another_directory_is_refused(self, make_user, api_client, signing_key):
        make_user(email='staff@accelirate.com')

        response = post_sso(api_client, make_token(
            signing_key, tid=OTHER_TENANT,
            iss=f'https://login.microsoftonline.com/{OTHER_TENANT}/v2.0',
        ))

        assert response.status_code == 401

    def test_a_tenant_that_disagrees_with_the_issuer_is_refused(self, make_user, api_client,
                                                                signing_key):
        """iss and tid are two claims that can disagree, which is why both are checked."""
        make_user(email='staff@accelirate.com')

        response = post_sso(api_client, make_token(signing_key, tid=OTHER_TENANT))

        assert response.status_code == 401

    def test_an_expired_token_is_refused(self, make_user, api_client, signing_key):
        make_user(email='staff@accelirate.com')
        now = int(time.time())

        response = post_sso(api_client, make_token(
            signing_key, iat=now - 7200, nbf=now - 7200, exp=now - 3600,
        ))

        assert response.status_code == 401

    def test_garbage_is_refused_without_raising(self, api_client):
        assert post_sso(api_client, 'not-a-jwt').status_code == 401
        assert post_sso(api_client, '').status_code == 401
        assert post_sso(api_client, None).status_code == 401


class TestWhoIsLetIn:
    def test_an_unknown_address_is_turned_away_by_name(self, api_client, signing_key):
        """No account is ever created. The message names the address so the person knows what
        to ask an administrator for, rather than retrying a password they do not have."""
        response = post_sso(api_client, make_token(signing_key))

        assert response.status_code == 401
        assert 'staff@accelirate.com' in response.data['detail']
        assert 'administrator' in response.data['detail'].lower()

    def test_no_account_is_created(self, api_client, signing_key):
        from api.models import User

        post_sso(api_client, make_token(signing_key))

        assert not User.objects.filter(email='staff@accelirate.com').exists()

    def test_a_deactivated_account_cannot_sign_in(self, make_user, api_client, signing_key):
        user = make_user(email='staff@accelirate.com')
        user.is_active = False
        user.save(update_fields=['is_active'])

        response = post_sso(api_client, make_token(signing_key))

        assert response.status_code == 401
        assert AuditLog.objects.filter(user=user, action_type='login_blocked').exists()

    def test_a_guest_in_the_directory_is_refused(self, make_user, api_client, signing_key):
        """In the tenant without being in the company - the same rule the password form
        applies. The account check never even runs."""
        response = post_sso(api_client, make_token(
            signing_key, preferred_username='guest@outlook.com',
        ))

        assert response.status_code == 401
        assert 'corporate' in response.data['detail'].lower()

    def test_the_email_claim_is_used_when_present(self, make_user, api_client, signing_key):
        """Entra populates preferred_username always and email only when configured, so both
        are tried rather than assuming one tenant's setup."""
        make_user(email='other@accelirate.com')

        response = post_sso(api_client, make_token(
            signing_key, email='other@accelirate.com',
            preferred_username='ignored@accelirate.com',
        ))

        assert response.status_code == 200


class TestTheSessionIsTheSameOne:
    def test_it_returns_the_same_shape_a_password_login_does(self, make_user, api_client,
                                                             signing_key, settings):
        make_user(email='staff@accelirate.com')

        response = post_sso(api_client, make_token(signing_key))

        assert set(response.data) == {'access_token', 'user'}
        assert settings.REFRESH_COOKIE_NAME in response.cookies

    def test_the_access_token_works_on_a_protected_endpoint(self, make_user, api_client,
                                                            signing_key):
        """The real assertion behind "SSO changes how identity is proven, not what a session
        is": the token it mints is accepted by the ordinary authentication class."""
        make_user(role='admin', email='staff@accelirate.com')
        token = post_sso(api_client, make_token(signing_key)).data['access_token']

        api_client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
        assert api_client.get('/api/dashboard/').status_code == 200

    def test_it_is_logged_as_its_own_action(self, make_user, api_client, signing_key):
        """The audit screen's job is answering how somebody got in, and a federated sign-in is
        a different answer from a password one."""
        user = make_user(email='staff@accelirate.com')

        post_sso(api_client, make_token(signing_key))

        assert AuditLog.objects.filter(user=user, action_type='login_sso').exists()
        assert not AuditLog.objects.filter(user=user, action_type='login').exists()

    def test_it_records_the_sign_in_time(self, make_user, api_client, signing_key):
        user = make_user(email='staff@accelirate.com')
        assert user.last_login_at is None

        post_sso(api_client, make_token(signing_key))

        user.refresh_from_db()
        assert user.last_login_at is not None
        assert timezone.now() - user.last_login_at < timedelta(minutes=1)


class TestWhenItIsSwitchedOff:
    def test_the_endpoint_refuses_when_unconfigured(self, settings, make_user, api_client,
                                                    signing_key):
        """A deployment with no registration must not have a half-working door."""
        make_user(email='staff@accelirate.com')
        settings.SSO_ENABLED = False

        response = post_sso(api_client, make_token(signing_key))

        assert response.status_code == 400

    @pytest.mark.parametrize('missing', ['SSO_CLIENT_ID', 'SSO_TENANT_ID'])
    def test_a_blank_setting_disables_it_rather_than_widening_it(self, settings, missing):
        """Blank must never mean "accept any audience" or "accept any tenant"."""
        setattr(settings, missing, '')

        assert sso.is_configured() is False
