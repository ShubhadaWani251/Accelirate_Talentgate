from django.conf import settings


def get_client_ip(request):
    """Best-effort client IP, honoring X-Forwarded-For only when explicitly trusted
    (settings.TRUST_X_FORWARDED_FOR) - see that setting's docstring for why this isn't
    on by default.
    """
    if settings.TRUST_X_FORWARDED_FOR:
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def ratelimit_ip_key(group, request):
    """Key function for django_ratelimit's `key=` option, consistent with get_client_ip."""
    return get_client_ip(request)


def ratelimit_user_key(group, request):
    """Per-user (not per-IP) rate-limit key for authenticated internal endpoints - several TAs
    can share an office IP, so limiting by IP there would throttle innocent users together.
    Permission checks (IsAdminOrTA) always run before the decorated method body, so
    request.user is guaranteed to be set here.
    """
    return str(request.user.user_id)


def ratelimit_token_key(group, request):
    """Per-invitation-token rate-limit key for the pre-attempt candidate exam endpoints (token
    landing, email verification, identity capture).

    Same reasoning as ratelimit_user_key above, for the same underlying problem: candidates
    sitting an in-person assessment normally share one office/lab/college IP (that is the
    ordinary shape of this app's real traffic, not an edge case), so keying these on IP means
    one candidate's activity can throttle every other candidate at the same location out of
    their own, entirely unrelated exam link. The URL already carries a real per-candidate
    identity - the invitation token - so keying on that instead bounds abuse of any ONE link
    regardless of source address, without one location's legitimate concurrency exhausting a
    shared bucket. Falls back to the IP only if the token could not be read from the resolved
    URL, which no caller of this key function should ever actually hit.
    """
    resolver_match = getattr(request, 'resolver_match', None)
    token = resolver_match.kwargs.get('token') if resolver_match else None
    return token or get_client_ip(request)


def ratelimit_attempt_key(group, request):
    """Per-attempt rate-limit key for authenticated candidate exam endpoints (e.g. recording
    chunk upload) - the CandidateAttemptAuthentication counterpart to ratelimit_user_key, and
    ratelimit_token_key's sibling for once an attempt exists. CandidateAttemptAuthentication
    always runs before the decorated method body, so request.user (the ExamAttempt itself - see
    api/authentication.py) is guaranteed to be set here.
    """
    return str(request.user.attempt_id)
