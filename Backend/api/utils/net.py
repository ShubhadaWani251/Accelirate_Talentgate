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
