"""Certificate-based (private_key_jwt) authentication for Microsoft Graph, as an alternative to
the client secret graph_email.py has used until now - see its module docstring for why. The
certificate itself is never something these tests touch Azure for; they only check that this app
builds and signs the assertion correctly, and picks the right auth mode.
"""

import datetime

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from api.services import graph_email


@pytest.fixture
def key_and_cert(tmp_path):
    """A throwaway self-signed cert/key pair, the same shape generate_graph_cert.py produces -
    written to a combined PEM file since that is what GRAPH_CERT_PATH points at.
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'test-cert')])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .sign(private_key, hashes.SHA256())
    )
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
    combined = tmp_path / 'key-and-cert.pem'
    combined.write_bytes(key_pem + cert_pem)
    thumbprint = certificate.fingerprint(hashes.SHA1()).hex()
    return {
        'path': str(combined),
        'thumbprint': thumbprint,
        'public_key': private_key.public_key(),
    }


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {'access_token': 'tok', 'expires_in': 3600}
        self.text = str(self._payload)

    def json(self):
        return self._payload


class TestBuildClientAssertion:
    def test_the_assertion_is_signed_and_verifiable_with_the_public_key(self, key_and_cert):
        token_url = 'https://login.microsoftonline.com/tenant-x/oauth2/v2.0/token'
        assertion = graph_email._build_client_assertion(
            token_url, 'client-x', key_and_cert['path'], key_and_cert['thumbprint'],
        )

        claims = jwt.decode(
            assertion, key_and_cert['public_key'], algorithms=['RS256'], audience=token_url,
        )
        assert claims['iss'] == 'client-x'
        assert claims['sub'] == 'client-x'
        assert claims['aud'] == token_url
        assert 'jti' in claims

    def test_the_header_carries_the_thumbprint_as_x5t(self, key_and_cert):
        assertion = graph_email._build_client_assertion(
            'https://login.microsoftonline.com/t/oauth2/v2.0/token', 'client-x',
            key_and_cert['path'], key_and_cert['thumbprint'],
        )

        header = jwt.get_unverified_header(assertion)
        assert 'x5t' in header
        # base64url of the raw thumbprint bytes, not the hex string itself - a common mistake
        # that produces a signature Azure AD cannot match to the uploaded certificate.
        assert header['x5t'] != key_and_cert['thumbprint']

    def test_a_wrong_public_key_fails_verification(self, key_and_cert):
        """Confirms the signature is actually checked, not just present - a broken signer that
        produced an unverifiable-but-well-formed JWT would pass a less careful test.
        """
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
        token_url = 'https://login.microsoftonline.com/t/oauth2/v2.0/token'
        assertion = graph_email._build_client_assertion(
            token_url, 'client-x', key_and_cert['path'], key_and_cert['thumbprint'],
        )
        with pytest.raises(jwt.InvalidSignatureError):
            jwt.decode(assertion, other_key, algorithms=['RS256'], audience=token_url)

    def test_a_missing_cert_file_raises_a_clear_error(self):
        with pytest.raises(graph_email.GraphEmailError, match='GRAPH_CERT_PATH'):
            graph_email._build_client_assertion(
                'https://login.microsoftonline.com/t/oauth2/v2.0/token', 'client-x',
                '/no/such/file.pem', 'aabbcc',
            )

    def test_an_invalid_thumbprint_raises_a_clear_error(self, key_and_cert):
        with pytest.raises(graph_email.GraphEmailError, match='GRAPH_CERT_THUMBPRINT'):
            graph_email._build_client_assertion(
                'https://login.microsoftonline.com/t/oauth2/v2.0/token', 'client-x',
                key_and_cert['path'], 'not-hex-at-all',
            )


class TestTokenFetchPicksTheRightAuthMode:
    def test_prefers_certificate_auth_when_both_are_configured(
        self, key_and_cert, settings, monkeypatch
    ):
        settings.GRAPH_TENANT_ID = 'tenant-x'
        settings.GRAPH_CLIENT_ID = 'client-x'
        settings.GRAPH_CLIENT_SECRET = 'a-secret-that-should-not-be-used'
        settings.GRAPH_CERT_PATH = key_and_cert['path']
        settings.GRAPH_CERT_THUMBPRINT = key_and_cert['thumbprint']

        captured = {}

        def fake_post(url, data=None, timeout=None):
            captured['url'] = url
            captured['data'] = data
            return _FakeResponse()

        monkeypatch.setattr(graph_email.requests, 'post', fake_post)

        cache = graph_email._TokenCache()
        token = cache.get()

        assert token == 'tok'
        assert 'client_assertion' in captured['data']
        assert captured['data']['client_assertion_type'] == (
            'urn:ietf:params:oauth:client-assertion-type:jwt-bearer'
        )
        assert 'client_secret' not in captured['data']

    def test_falls_back_to_the_secret_when_no_cert_is_configured(self, settings, monkeypatch):
        settings.GRAPH_TENANT_ID = 'tenant-x'
        settings.GRAPH_CLIENT_ID = 'client-x'
        settings.GRAPH_CLIENT_SECRET = 'a-real-secret'
        settings.GRAPH_CERT_PATH = ''
        settings.GRAPH_CERT_THUMBPRINT = ''

        captured = {}

        def fake_post(url, data=None, timeout=None):
            captured['data'] = data
            return _FakeResponse()

        monkeypatch.setattr(graph_email.requests, 'post', fake_post)

        cache = graph_email._TokenCache()
        token = cache.get()

        assert token == 'tok'
        assert captured['data']['client_secret'] == 'a-real-secret'
        assert 'client_assertion' not in captured['data']

    def test_neither_secret_nor_cert_raises_clearly(self, settings):
        settings.GRAPH_TENANT_ID = 'tenant-x'
        settings.GRAPH_CLIENT_ID = 'client-x'
        settings.GRAPH_CLIENT_SECRET = ''
        settings.GRAPH_CERT_PATH = ''
        settings.GRAPH_CERT_THUMBPRINT = ''

        cache = graph_email._TokenCache()
        with pytest.raises(graph_email.GraphEmailError, match='GRAPH_CLIENT_SECRET'):
            cache.get()

    def test_a_cert_path_with_no_thumbprint_falls_back_to_the_secret(
        self, key_and_cert, settings, monkeypatch
    ):
        """Both have to be set together - a half-configured cert should not silently produce a
        broken assertion when a perfectly good secret is sitting right there.
        """
        settings.GRAPH_TENANT_ID = 'tenant-x'
        settings.GRAPH_CLIENT_ID = 'client-x'
        settings.GRAPH_CLIENT_SECRET = 'a-real-secret'
        settings.GRAPH_CERT_PATH = key_and_cert['path']
        settings.GRAPH_CERT_THUMBPRINT = ''

        captured = {}

        def fake_post(url, data=None, timeout=None):
            captured['data'] = data
            return _FakeResponse()

        monkeypatch.setattr(graph_email.requests, 'post', fake_post)

        cache = graph_email._TokenCache()
        assert cache.get() == 'tok'
        assert captured['data']['client_secret'] == 'a-real-secret'
