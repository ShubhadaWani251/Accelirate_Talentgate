from django.conf import settings
from django.contrib.auth.hashers import check_password

from api.models import PasswordHistoryEntry


def is_password_reused(user, raw_password):
    """True if raw_password matches the user's current password or any of their
    last settings.PASSWORD_HISTORY_COUNT passwords.
    """
    if user.check_password(raw_password):
        return True

    recent = (
        PasswordHistoryEntry.objects
        .filter(user=user)
        .order_by('-created_at')[:settings.PASSWORD_HISTORY_COUNT]
    )
    return any(check_password(raw_password, entry.password_hash) for entry in recent)


def record_password_history(user):
    """Archive the user's outgoing password hash and prune anything beyond the
    configured history length. Call this BEFORE user.set_password() overwrites
    user.password_hash with the new value.
    """
    PasswordHistoryEntry.objects.create(user=user, password_hash=user.password_hash)

    keep_ids = list(
        PasswordHistoryEntry.objects
        .filter(user=user)
        .order_by('-created_at')
        .values_list('history_id', flat=True)[:settings.PASSWORD_HISTORY_COUNT]
    )
    PasswordHistoryEntry.objects.filter(user=user).exclude(history_id__in=keep_ids).delete()
