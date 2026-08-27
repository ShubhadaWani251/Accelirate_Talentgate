"""Django email backend that sends through the Microsoft Graph API.

Replaces SendGrid. Every existing `send_mail(...)` call keeps working unchanged - swapping
EMAIL_BACKEND is the whole integration, which is why the app's send sites needed no rewrite.

Why Graph rather than SendGrid: mail sent through Graph originates inside the Accelirate M365
tenant, so it isn't subject to the external-sender quarantine that has been holding candidate
invites and OTP codes for @accelirate.com recipients.

Auth is the OAuth2 client-credentials (app-only) flow, so the app sends as a fixed mailbox with
no user signed in. That requires an Azure AD app registration with the **application** permission
`Mail.Send` (not delegated), admin-consented, and a mailbox it is allowed to send as.

Two ways to authenticate as the app - both use the same client-credentials grant, they just
prove the app's identity differently:

    GRAPH_TENANT_ID           directory (tenant) ID of the Azure AD app registration
    GRAPH_CLIENT_ID           application (client) ID
    GRAPH_SENDER               mailbox to send as, e.g. talentgate@accelirate.com

    GRAPH_CLIENT_SECRET       a shared secret value - simplest to set up, the default
    -- or --
    GRAPH_CERT_PATH +          a certificate's private key, presented as a signed JWT
    GRAPH_CERT_THUMBPRINT      (private_key_jwt) - stronger, no shared secret to leak or expire
                                unnoticed. Preferred when both are set; falls back to
                                GRAPH_CLIENT_SECRET otherwise. See
                                api/management/commands/generate_graph_cert.py to produce the
                                key pair and the exact values these two settings need.
"""

import base64
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone

import jwt
import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

_TOKEN_URL = 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token'
_SEND_URL = 'https://graph.microsoft.com/v1.0/users/{sender}/sendMail'
_SCOPE = 'https://graph.microsoft.com/.default'

# Refresh a little before actual expiry so a token can't lapse mid-request.
_EXPIRY_SKEW_SECONDS = 120


class GraphEmailError(Exception):
    """Raised when Graph rejects a send or the token cannot be obtained.

    The invite/OTP/notification services catch this to mark delivery failed, exactly as they
    previously caught AnymailError.
    """


def _build_client_assertion(token_url, client_id, cert_path, thumbprint_hex):
    """A JWT the app signs with its own certificate's private key, presented to Azure AD in
    place of a client secret (RFC 7523 private_key_jwt - Azure AD's supported form of
    certificate-based app authentication). Short-lived on purpose (5 minutes): unlike a client
    secret, a leaked assertion is useless almost immediately, since it is minted fresh here on
    every token fetch rather than being a long-lived credential in its own right.

    x5t is the certificate's SHA-1 thumbprint, base64url-encoded - it is how Azure AD knows
    which of the app registration's uploaded certificates to verify the signature against, so it
    has to be exactly the thumbprint Azure shows for that certificate (GRAPH_CERT_THUMBPRINT),
    not anything derived from the private key file itself.
    """
    try:
        with open(cert_path, 'rb') as f:
            private_key = f.read()
    except OSError as exc:
        raise GraphEmailError(f'Could not read GRAPH_CERT_PATH ({cert_path}): {exc}') from exc

    try:
        thumbprint_bytes = bytes.fromhex(thumbprint_hex.strip())
    except ValueError as exc:
        raise GraphEmailError(
            f'GRAPH_CERT_THUMBPRINT is not valid hex: {thumbprint_hex!r}'
        ) from exc
    x5t = base64.urlsafe_b64encode(thumbprint_bytes).decode().rstrip('=')

    now = datetime.now(dt_timezone.utc)
    claims = {
        'iss': client_id,
        'sub': client_id,
        'aud': token_url,
        'jti': str(uuid.uuid4()),
        'nbf': now,
        'exp': now + timedelta(minutes=5),
    }
    try:
        return jwt.encode(claims, private_key, algorithm='RS256', headers={'x5t': x5t})
    except Exception as exc:
        raise GraphEmailError(
            f'Could not sign the certificate-based client assertion: {exc}'
        ) from exc


class _TokenCache:
    """Process-wide access token, refreshed on expiry.

    Tokens last ~60 minutes, so fetching one per email would add a needless round-trip to
    Microsoft on every send. Guarded by a lock because emails are dispatched from background
    threads (see services/invites.py) and several can start at once.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._token = None
        self._expires_at = 0.0

    def get(self):
        with self._lock:
            if self._token and time.monotonic() < self._expires_at:
                return self._token
            self._token, lifetime = self._fetch()
            self._expires_at = time.monotonic() + max(lifetime - _EXPIRY_SKEW_SECONDS, 0)
            return self._token

    def _fetch(self):
        tenant = getattr(settings, 'GRAPH_TENANT_ID', '')
        client_id = getattr(settings, 'GRAPH_CLIENT_ID', '')
        if not tenant or not client_id:
            raise GraphEmailError(
                'Microsoft Graph is not configured - missing GRAPH_TENANT_ID/GRAPH_CLIENT_ID.'
            )
        token_url = _TOKEN_URL.format(tenant=tenant)

        cert_path = getattr(settings, 'GRAPH_CERT_PATH', '')
        cert_thumbprint = getattr(settings, 'GRAPH_CERT_THUMBPRINT', '')
        if cert_path and cert_thumbprint:
            # Preferred over the secret whenever both are configured - see the module docstring.
            request_data = {
                'client_id': client_id,
                'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
                'client_assertion': _build_client_assertion(
                    token_url, client_id, cert_path, cert_thumbprint,
                ),
                'scope': _SCOPE,
                'grant_type': 'client_credentials',
            }
        else:
            client_secret = getattr(settings, 'GRAPH_CLIENT_SECRET', '')
            if not client_secret:
                raise GraphEmailError(
                    'Microsoft Graph is not configured - set either GRAPH_CLIENT_SECRET, or '
                    'both GRAPH_CERT_PATH and GRAPH_CERT_THUMBPRINT.'
                )
            request_data = {
                'client_id': client_id,
                'client_secret': client_secret,
                'scope': _SCOPE,
                'grant_type': 'client_credentials',
            }

        try:
            response = requests.post(token_url, data=request_data, timeout=15)
        except requests.RequestException as exc:
            raise GraphEmailError(f'Could not reach Microsoft login endpoint: {exc}') from exc

        if response.status_code != 200:
            # Surface Azure's own error description - it distinguishes a wrong secret from a
            # missing consent from a wrong tenant, which is most of the setup pain.
            raise GraphEmailError(
                f'Graph token request failed ({response.status_code}): '
                f'{_describe(response)}'
            )

        payload = response.json()
        return payload['access_token'], int(payload.get('expires_in', 3600))


def _describe(response):
    """Best-effort human-readable reason out of a Graph/AAD error response."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if 'error_description' in body:
        return str(body['error_description']).splitlines()[0][:300]
    error = body.get('error')
    if isinstance(error, dict):
        return f"{error.get('code')}: {error.get('message')}"[:300]
    return str(body)[:300]


_token_cache = _TokenCache()


def _recipients(addresses):
    return [{'emailAddress': {'address': address}} for address in addresses if address]


def _to_graph_message(message):
    """Convert a Django EmailMessage into Graph's sendMail payload.

    Handles the html alternative that EmailMultiAlternatives attaches, since the OTP and invite
    mails may gain HTML bodies later; a plain-text-only message just sends as text.
    """
    body_type, body_content = 'Text', message.body
    for content, mimetype in getattr(message, 'alternatives', []) or []:
        if mimetype == 'text/html':
            body_type, body_content = 'HTML', content
            break

    payload = {
        'message': {
            'subject': message.subject,
            'body': {'contentType': body_type, 'content': body_content},
            'toRecipients': _recipients(message.to),
        },
        # The service mailbox would otherwise accumulate a copy of every candidate invite.
        'saveToSentItems': bool(getattr(settings, 'GRAPH_SAVE_TO_SENT_ITEMS', False)),
    }
    if message.cc:
        payload['message']['ccRecipients'] = _recipients(message.cc)
    if message.bcc:
        payload['message']['bccRecipients'] = _recipients(message.bcc)
    if message.reply_to:
        payload['message']['replyTo'] = _recipients(message.reply_to)
    return payload


class GraphEmailBackend(BaseEmailBackend):
    """Sends each message with one Graph sendMail call.

    Graph has no batch send endpoint, so this is one HTTPS request per recipient message -
    the same shape SendGrid had. Sends already run on a background thread, so the request
    handler doesn't wait on them.
    """

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        sender = getattr(settings, 'GRAPH_SENDER', '') or settings.DEFAULT_FROM_EMAIL
        if not sender:
            raise GraphEmailError('No sender configured - set GRAPH_SENDER or DEFAULT_FROM_EMAIL.')

        token = _token_cache.get()
        url = _SEND_URL.format(sender=sender)
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

        sent = 0
        for message in email_messages:
            if not message.to:
                # Django's SMTP backend silently counts a recipient-less message as sent, which
                # is how blank candidate emails went unnoticed for so long. Skip it visibly.
                logger.warning('Skipping email "%s" - no recipients', message.subject)
                continue
            try:
                response = requests.post(url, headers=headers,
                                         json=_to_graph_message(message), timeout=30)
            except requests.RequestException as exc:
                if not self.fail_silently:
                    raise GraphEmailError(f'Could not reach Microsoft Graph: {exc}') from exc
                logger.exception('Graph send failed for "%s"', message.subject)
                continue

            # sendMail returns 202 Accepted with an empty body on success.
            if response.status_code not in (200, 202):
                if not self.fail_silently:
                    raise GraphEmailError(
                        f'Graph refused to send "{message.subject}" '
                        f'({response.status_code}): {_describe(response)}'
                    )
                logger.error('Graph send failed for "%s": %s', message.subject, _describe(response))
                continue
            sent += 1
        return sent
