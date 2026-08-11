from django.core.cache import cache

LOCKOUT_THRESHOLD = 5
LOCKOUT_WINDOW_SECONDS = 15 * 60


def _key(email):
    return f'login_fail:{email.strip().lower()}'


def is_locked_out(email):
    return cache.get(_key(email), 0) >= LOCKOUT_THRESHOLD


def register_failed_attempt(email):
    """Increment the failed-attempt counter for this email, keyed by the raw submitted
    string (not a resolved user id) so nonexistent-account guessing sprees are throttled
    identically to real-account brute force - no extra signal either way.
    """
    key = _key(email)
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=LOCKOUT_WINDOW_SECONDS)
        return 1


def clear_failed_attempts(email):
    cache.delete(_key(email))
