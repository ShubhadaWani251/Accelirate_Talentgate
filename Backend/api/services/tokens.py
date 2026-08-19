from datetime import datetime, timedelta, timezone as dt_timezone

from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from api.models import RevokedRefreshToken

USER_ID_CLAIM = 'user_id'


def issue_tokens_for_user(user):
    """Mint a fresh access/refresh pair for the given api.User.

    Deliberately does not use RefreshToken.for_user() - that classmethod
    assumes the user model it's given matches AUTH_USER_MODEL, which api.User
    is not (see api/authentication.py). Setting the claim directly sidesteps that.
    """
    refresh = RefreshToken()
    refresh[USER_ID_CLAIM] = user.user_id
    access = refresh.access_token
    return str(refresh), str(access)


def issue_attempt_token(attempt):
    """Mint a short-lived access token scoped to one ExamAttempt - the candidate-portal
    equivalent of issue_tokens_for_user, but with no refresh-rotation counterpart: a lost or
    expired token just means resuming via /t/<token> again (see views/exam.py), so there's
    nothing to revoke or rotate.

    Lifetime is the exam's own duration plus a small grace window, not SIMPLE_JWT's default -
    CandidateAttemptAuthentication independently re-checks the real deadline
    (started_at + exam_duration_minutes) on every request, so this JWT expiry is only a backstop
    against a stale token being replayed long after the exam window closed.
    """
    token = AccessToken()
    token['attempt_id'] = attempt.attempt_id
    token.set_exp(lifetime=timedelta(minutes=attempt.invitation.batch.exam_duration_minutes + 10))
    return str(token)


def revoke_refresh_token(raw_token):
    """Validate a raw refresh token string and add its jti to the denylist."""
    try:
        token = RefreshToken(raw_token)
    except TokenError:
        return
    RevokedRefreshToken.objects.get_or_create(
        jti=token['jti'],
        defaults={
            'user_id': token[USER_ID_CLAIM],
            'expires_at': datetime.fromtimestamp(token['exp'], tz=dt_timezone.utc),
        },
    )


def token_issued_before_password_change(token, user):
    """True if this token predates the user's last password change/reset - such
    tokens are treated as stale so changing a password immediately invalidates
    any other outstanding sessions (e.g. a stolen refresh token).
    """
    if not user.password_changed_at:
        return False
    return token['iat'] < int(user.password_changed_at.timestamp())


def rotate_refresh_token(raw_token):
    """Validate a raw refresh token, ensure it hasn't been revoked or gone stale, and
    issue a new access/refresh pair - revoking the old refresh token in the process.

    Raises TokenError if the token is invalid, expired, revoked, or stale.
    """
    token = RefreshToken(raw_token)
    if RevokedRefreshToken.objects.filter(jti=token['jti']).exists():
        raise TokenError('Token is revoked')

    from api.models import User
    try:
        user = User.objects.get(user_id=token[USER_ID_CLAIM], is_active=True, is_deleted=False)
    except User.DoesNotExist:
        raise TokenError('User not found or inactive')

    if token_issued_before_password_change(token, user):
        raise TokenError('Token predates a password change')

    revoke_refresh_token(raw_token)
    return issue_tokens_for_user(user), user
