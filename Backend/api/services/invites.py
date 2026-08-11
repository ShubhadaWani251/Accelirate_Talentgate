import logging
import secrets
import threading

from anymail.exceptions import AnymailError
from django.conf import settings
from django.core.mail import send_mail
from django.db import connections
from django.utils import timezone

from api.models import Candidate, Invitation

logger = logging.getLogger(__name__)


def _generate_token():
    return secrets.token_urlsafe(32)[:64]


def create_invitations(batch, user):
    """Create one Invitation per eligible (OK-validated, still pending) candidate on this
    batch and flip their status to INVITED. Email sending itself is a separate, async step
    (see send_invites_async) - status reflects "invite issued", not "email delivered"
    (see Invitation.email_status for the latter).
    """
    invitations = []
    candidates = batch.candidate_set.filter(
        status=Candidate.Status.PENDING_INVITE,
        validation_status=Candidate.ValidationStatus.OK,
        is_deleted=False,
    )
    for candidate in candidates:
        invitation = Invitation.objects.create(
            candidate=candidate,
            batch=batch,
            unique_link_token=_generate_token(),
            link_expired_at=batch.link_valid_until,
            sent_by=user,
        )
        candidate.status = Candidate.Status.INVITED
        candidate.save(update_fields=['status'])
        invitations.append(invitation)
    return invitations


def send_invite_email(invitation, base_url):
    candidate = invitation.candidate
    batch = invitation.batch
    link = f"{base_url.rstrip('/')}/t/{invitation.unique_link_token}"
    send_mail(
        subject=f'Accelirate TalentGate - Assessment Invitation ({batch.batch_name})',
        message=(
            f"Hello {candidate.full_name},\n\n"
            f"You have been invited to complete an online assessment for {batch.college_name}.\n\n"
            f"Link: {link}\n"
            f"Available: {batch.link_valid_from.strftime('%d-%b-%Y %I:%M %p')} - "
            f"{batch.link_valid_until.strftime('%d-%b-%Y %I:%M %p')}\n"
            f"Duration: {batch.exam_duration_minutes} minutes\n\n"
            "Please have a government ID ready and ensure a working camera before you begin.\n"
            "If you have questions, contact your recruiting coordinator."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[candidate.email],
        fail_silently=False,
    )


def send_invites_async(invitations, base_url):
    """Fire off all invite emails on a single background thread (sequential, not one
    thread per candidate) - keeps the finalize/send-invites request fast regardless of
    batch size. Delivery outcome is tracked per-invitation via email_status.
    """
    def _worker():
        try:
            for invitation in invitations:
                try:
                    send_invite_email(invitation, base_url)
                    invitation.email_status = Invitation.EmailStatus.SENT
                    invitation.email_sent_at = timezone.now()
                    invitation.save(update_fields=['email_status', 'email_sent_at'])
                except AnymailError:
                    logger.exception(
                        'Failed to send invite email for invitation_id=%s', invitation.invitation_id
                    )
                    invitation.email_status = Invitation.EmailStatus.FAILED
                    invitation.save(update_fields=['email_status'])
        finally:
            connections.close_all()

    threading.Thread(target=_worker, daemon=True).start()
