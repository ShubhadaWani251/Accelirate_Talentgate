import logging
import secrets
import threading

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.mail import send_mail
from django.db import connections, transaction
from django.utils import timezone

from api.models import OTPVerification
from api.services.email_errors import EMAIL_SEND_ERRORS

logger = logging.getLogger(__name__)


class OtpCooldownError(Exception):
    """Raised when an OTP was requested again before the resend cooldown elapsed."""

    def __init__(self, retry_after_seconds):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Retry after {retry_after_seconds}s")


class OtpDeliveryError(Exception):
    """Raised when the OTP email itself fails to send (e.g. email provider misconfigured)."""


def generate_otp():
    """Cryptographically random 6-digit numeric code."""
    return f"{secrets.randbelow(1_000_000):06d}"


def issue_otp(user, purpose=OTPVerification.Purpose.PASSWORD_RESET, async_send=False):
    """Create and email a fresh OTP for the given user, enforcing the resend cooldown.

    async_send=True fires the actual email send on a background thread and returns as
    soon as the OTP row is created. This is used by the two public, unauthenticated
    endpoints (forgot-password, resend-otp) so their response time doesn't leak whether
    the email belongs to a real account - a real SendGrid API call is far slower than a
    DB miss, which is otherwise a textbook account-enumeration timing side-channel.
    Delivery failures in that mode are only logged, not raised, since there's no request
    left to report them to.
    """
    cooldown = settings.OTP_RESEND_COOLDOWN_SECONDS
    latest = (
        OTPVerification.objects
        .filter(user=user, purpose=purpose, verified_at__isnull=True)
        .order_by('-created_at')
        .first()
    )
    if latest:
        elapsed = (timezone.now() - latest.created_at).total_seconds()
        if elapsed < cooldown:
            raise OtpCooldownError(retry_after_seconds=int(cooldown - elapsed))

    code = generate_otp()

    if async_send:
        otp = OTPVerification.objects.create(
            user=user,
            otp_code_hash=make_password(code),
            purpose=purpose,
            expires_at=timezone.now() + timezone.timedelta(minutes=settings.OTP_EXPIRY_MINUTES),
        )
        _send_otp_email_background(user, code)
        return otp

    try:
        with transaction.atomic():
            otp = OTPVerification.objects.create(
                user=user,
                otp_code_hash=make_password(code),
                purpose=purpose,
                expires_at=timezone.now() + timezone.timedelta(minutes=settings.OTP_EXPIRY_MINUTES),
            )
            send_otp_email(user, code)
    except EMAIL_SEND_ERRORS:
        logger.exception('Failed to send OTP email to user_id=%s', user.user_id)
        raise OtpDeliveryError('Could not send the verification email. Please try again later.')
    return otp


def _send_otp_email_background(user, code):
    def _worker():
        try:
            send_otp_email(user, code)
        except EMAIL_SEND_ERRORS:
            logger.exception('Background OTP email send failed for user_id=%s', user.user_id)
        finally:
            connections.close_all()

    threading.Thread(target=_worker, daemon=True).start()


def send_otp_email(user, code):
    send_mail(
        subject='Accelirate TalentGate - Password Reset Code',
        message=(
            f"Hello {user.first_name},\n\n"
            f"Your one-time password reset code is: {code}\n"
            f"This code expires in {settings.OTP_EXPIRY_MINUTES} minutes.\n\n"
            "If you did not request this, you can safely ignore this email."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )
