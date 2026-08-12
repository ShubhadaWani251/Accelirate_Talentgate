import logging
import secrets
import string
import threading

from anymail.exceptions import AnymailError
from django.conf import settings
from django.core.mail import send_mail
from django.db import connections

from api.models import User

logger = logging.getLogger(__name__)

_PASSWORD_ALPHABET = string.ascii_letters + string.digits + '!@#$%^&*'


def generate_temp_password(length=16):
    """A random password that satisfies the app's complexity validator (upper/lower/digit/
    special char) with very high probability by construction, then reshuffled so the fixed
    positions aren't guessable.
    """
    password = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice('!@#$%^&*'),
    ]
    password += [secrets.choice(_PASSWORD_ALPHABET) for _ in range(length - len(password))]
    secrets.SystemRandom().shuffle(password)
    return ''.join(password)


def create_user_with_credentials(data, created_by):
    """Create a User from validated UserCreateSerializer data, assign a random temp
    password, and email it on a background thread - same fire-and-forget pattern as
    services/invites.py, so the request doesn't wait on SendGrid.
    """
    # email has a real DB-level unique constraint, so a soft-deleted row with this same
    # email (freed at the validation layer, but still physically occupying the column) would
    # otherwise cause an IntegrityError here - rename it out of the way, keeping the deleted
    # user's history intact under a non-colliding value.
    stale = User.objects.filter(email__iexact=data['email'], is_deleted=True).first()
    if stale:
        stale.email = f'deleted-{stale.user_id}-{stale.email}'
        stale.save(update_fields=['email'])

    temp_password = generate_temp_password()
    user = User(
        first_name=data['first_name'],
        last_name=data.get('last_name') or '',
        email=data['email'],
        role=data['role'],
        created_by=created_by,
    )
    user.set_password(temp_password)
    user.save()
    _send_credentials_email_background(user, temp_password)
    return user


def send_new_user_credentials_email(user, temp_password):
    send_mail(
        subject='Accelirate TalentGate - Your Account Has Been Created',
        message=(
            f"Hello {user.first_name},\n\n"
            f"An Administrator has created a TalentGate account for you.\n\n"
            f"Email: {user.email}\n"
            f"Temporary Password: {temp_password}\n\n"
            "Please log in and change your password from your Profile page as soon as "
            "possible.\n\n"
            "If you weren't expecting this account, please contact your Administrator."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


def _send_credentials_email_background(user, temp_password):
    def _worker():
        try:
            send_new_user_credentials_email(user, temp_password)
        except AnymailError:
            logger.exception('Failed to send new-user credentials email to user_id=%s', user.user_id)
        finally:
            connections.close_all()

    threading.Thread(target=_worker, daemon=True).start()
