"""Validate a Microsoft Entra ID token and resolve it to an api.User.

Validating the token is the ONLY thing single sign-on adds to authentication. Once a token is
trusted and an account matched, views/auth.SsoLoginView issues exactly the same JWT pair a
password login does (services/tokens.issue_tokens_for_user) and sets the same refresh cookie,
so everything downstream - CustomJWTAuthentication, roles, the idle logout, the audit log - is
untouched and cannot drift. SSO is a second front door, not a second session system.

WHAT THIS DELIBERATELY DOES NOT DO: it never creates an account. A token proves who someone is
in the directory; it says nothing about whether they should be able to read candidate records
here. Access stays where it already lives, in Admin -> Users, and an unknown address is turned
away (see views/auth.SsoLoginView). Auto-provisioning would mean everyone in the tenant
silently gaining a role nobody chose for them.

ON ACCEPTING AN ID TOKEN FROM THE BROWSER. The SPA signs in with MSAL and forwards the
resulting ID token here. The alternative - an authorization-code flow where this server
redeems the code against Entra itself - never puts a token in the browser at all, and is the
stronger pattern. The checks below are what make this one safe enough to prefer for its much
smaller moving-part count:

  signature   against the tenant's published JWKS, so the token was minted by Entra
  aud         equals OUR client id, so a token issued for a different application is refused
  iss + tid   equal OUR tenant, so a token from any other directory is refused
  exp/nbf     inside its validity window, with only a few seconds of clock leeway

The residual risk is replay of a stolen token inside its own short lifetime, over HTTPS, which
is the same exposure as the access token the browser already holds. `nonce` is NOT checked
here and cannot usefully be: it binds a token to the browser request that asked for it, which
only the SPA knows. MSAL validates it there. If this ever needs to be airtight, the answer is
the code flow above, not more checks in this file.
"""

import logging
import threading

import jwt
from django.conf import settings
from jwt import PyJWKClient

from api.utils.validation import is_corporate_email

logger = logging.getLogger(__name__)

_ISSUER_TEMPLATE = 'https://login.microsoftonline.com/{tenant}/v2.0'
_JWKS_URL_TEMPLATE = 'https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys'

# Entra signing keys roll, so the client caches them and refetches on an unknown kid rather
# than this module pinning anything. A few seconds of leeway absorbs clock skew between Entra
# and this server without meaningfully widening the window a dead token stays usable.
_CLOCK_LEEWAY_SECONDS = 30

_jwks_client = None
_jwks_lock = threading.Lock()


class SsoError(Exception):
    """A token that cannot be trusted, or a tenant/account that must not be let in.

    Carries a message safe to show the person trying to sign in. Nothing here distinguishes
    "no such account" from "wrong tenant" to the CALLER on purpose - see the view, which
    decides what each case says.
    """


def is_configured():
    """Whether SSO can run at all. False leaves the password form as the only way in."""
    return bool(settings.SSO_ENABLED and settings.SSO_CLIENT_ID and settings.SSO_TENANT_ID)


def _jwks():
    """One cached JWKS client for the process.

    Lazily built, like services/blob_storage's client: constructing it reaches out to Entra,
    which must not happen at import time - that would make the whole app refuse to start
    whenever Entra is slow or SSO is misconfigured, including for password logins that do not
    need it at all.
    """
    global _jwks_client
    if _jwks_client is None:
        with _jwks_lock:
            if _jwks_client is None:
                _jwks_client = PyJWKClient(
                    _JWKS_URL_TEMPLATE.format(tenant=settings.SSO_TENANT_ID),
                    cache_keys=True,
                )
    return _jwks_client


def _reset_jwks_cache():
    """Drop the cached client. Tests use this; nothing in the app does."""
    global _jwks_client
    with _jwks_lock:
        _jwks_client = None


def validate_id_token(raw_token):
    """Verify an Entra ID token and return {'email', 'object_id', 'name'}.

    Raises SsoError for anything that fails. The message is deliberately the same for every
    cryptographic failure: an attacker probing with forged tokens learns nothing from it, and
    the person who merely hit a stale session needs "sign in again", not a reason.
    """
    if not is_configured():
        raise SsoError('Single sign-on is not configured.')

    if not raw_token or not isinstance(raw_token, str):
        raise SsoError('Sign-in could not be completed. Please try again.')

    try:
        signing_key = _jwks().get_signing_key_from_jwt(raw_token)
        claims = jwt.decode(
            raw_token,
            signing_key.key,
            algorithms=['RS256'],
            audience=settings.SSO_CLIENT_ID,
            issuer=_ISSUER_TEMPLATE.format(tenant=settings.SSO_TENANT_ID),
            leeway=_CLOCK_LEEWAY_SECONDS,
            options={'require': ['exp', 'iat', 'aud', 'iss']},
        )
    except jwt.PyJWTError as exc:
        # Logged in full, returned as nothing: the reason a token failed is exactly the kind of
        # detail that helps someone craft a token that does not.
        logger.warning('Rejected an SSO token: %s', exc)
        raise SsoError('Sign-in could not be completed. Please try again.') from exc
    except Exception as exc:
        # Reaching Entra for the JWKS can fail on its own - a network blip should read as a
        # temporary fault, not as a rejected identity.
        logger.exception('Could not verify an SSO token')
        raise SsoError('Sign-in is temporarily unavailable. Please try again shortly.') from exc

    # Checked even though `iss` above already encodes the tenant. They are two claims that can
    # disagree, and a mismatch is the signature of a token being replayed across directories.
    tenant = claims.get('tid')
    if tenant != settings.SSO_TENANT_ID:
        logger.warning('Rejected an SSO token from tenant %r', tenant)
        raise SsoError('This account is not part of the organisation directory.')

    # Entra puts the sign-in address in `preferred_username` for work accounts and `email` when
    # the optional claim is configured. Neither is guaranteed, so both are tried before giving
    # up rather than assuming one tenant's configuration.
    email = (claims.get('email') or claims.get('preferred_username') or '').strip().lower()
    if not email:
        raise SsoError('That account has no email address, so it cannot be matched here.')

    if not is_corporate_email(email):
        # The same rule the password form applies (views/auth.LoginView). A guest in the
        # directory is in the tenant without being in the company.
        raise SsoError('Use your corporate email address to sign in.')

    return {
        'email': email,
        # Entra's immutable per-user id. Not used to match an account today - accounts are
        # keyed on email, which is what Admin -> Users collects - but it is the only stable
        # handle if that ever needs to survive someone's address changing.
        'object_id': claims.get('oid') or '',
        'name': (claims.get('name') or '').strip(),
    }
