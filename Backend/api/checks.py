"""Deployment-time system checks, surfaced by `manage.py check --deploy`.

These cover misconfigurations that Django's own checks don't know about but that silently
weaken this app in particular. Each one is a warning rather than an error: every situation
below is legitimate in some deployment, and refusing to start would be wrong.
"""

from django.conf import settings
from django.core.checks import Warning as CheckWarning, register, Tags


@register(Tags.caches, deploy=True)
def check_shared_cache_configured(app_configs, **kwargs):
    """Rate limiting and login lockout both count in the default cache.

    Django's default is LocMemCache, which is per-process. Under any multi-worker server
    (gunicorn's default is several) each worker keeps its own counters, so a '5/m' limit
    becomes 5-per-minute *per worker* and the login lockout can be sidestepped by being
    load-balanced onto a different one. The counting is silently wrong rather than broken,
    which is why this needs flagging rather than discovering later.
    """
    if settings.DEBUG:
        return []
    backend = settings.CACHES['default']['BACKEND'] if getattr(settings, 'CACHES', None) else \
        'django.core.cache.backends.locmem.LocMemCache'
    if 'locmem' not in backend.lower():
        return []
    return [CheckWarning(
        'Rate limiting and login lockout are counting in a per-process cache.',
        hint='LocMemCache is not shared between worker processes, so every rate limit is '
             'effectively multiplied by the worker count and the login lockout can be evaded '
             'by landing on a different worker. Set REDIS_URL to a shared Redis instance '
             '(the redis package is already a pinned dependency).',
        id='api.W001',
    )]


@register(Tags.security, deploy=True)
def check_evidence_storage_configured(app_configs, **kwargs):
    """Proctoring evidence has nowhere to go if Azure isn't configured.

    The local-disk fallback in services/blob_storage.py is gated on DEBUG, so with DEBUG=False
    and no connection string the first identity capture of the first real exam raises -
    mid-exam, for a candidate who has done nothing wrong.
    """
    if settings.DEBUG or settings.AZURE_STORAGE_CONNECTION_STRING:
        return []
    return [CheckWarning(
        'No Azure Blob Storage connection string configured for proctoring evidence.',
        hint='AZURE_STORAGE_CONNECTION_STRING is unset and the local-disk fallback only works '
             'with DEBUG=True. Identity photo upload will fail during the first real exam. '
             'See api/services/blob_storage.py.',
        id='api.W002',
    )]


@register(Tags.security, deploy=True)
def check_support_email_set(app_configs, **kwargs):
    """SUPPORT_EMAIL is printed in candidate invitation emails as the contact address."""
    if settings.DEBUG or settings.SUPPORT_EMAIL:
        return []
    return [CheckWarning(
        'SUPPORT_EMAIL is not set, so invitation emails fall back to the noreply address.',
        hint='Candidates are told to contact this address about technical problems with their '
             'assessment. Set it to a monitored mailbox.',
        id='api.W003',
    )]


@register(Tags.security, deploy=True)
def check_corporate_domains_not_public(app_configs, **kwargs):
    """A public webmail domain in CORPORATE_EMAIL_DOMAINS widens who can be provisioned."""
    public = {'gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com', 'live.com', 'icloud.com'}
    found = sorted(public.intersection(settings.CORPORATE_EMAIL_DOMAINS))
    if settings.DEBUG or not found:
        return []
    return [CheckWarning(
        f'CORPORATE_EMAIL_DOMAINS includes public webmail domain(s): {", ".join(found)}.',
        hint='This gates which addresses can hold a staff account. A public domain here was '
             'added for deliverability testing and should not survive into production. See '
             'CORPORATE_EMAIL_DOMAIN in .env.',
        id='api.W004',
    )]
