import logging
import secrets
import threading

from django.conf import settings
from django.core.mail import send_mail
from django.db import connections
from django.utils import timezone

from api.models import Candidate, Invitation
from api.services.email_errors import EMAIL_SEND_ERRORS

logger = logging.getLogger(__name__)


def _generate_token():
    return secrets.token_urlsafe(32)[:64]


def create_invitations(batch, user, candidate_ids=None):
    """Create one Invitation per eligible (OK-validated, still pending) candidate on this
    batch and flip their status to INVITED. Email sending itself is a separate, async step
    (see send_invites_async) - status reflects "invite issued", not "email delivered"
    (see Invitation.email_status for the latter).

    `candidate_ids` narrows this to an explicit subset - the reviewer's checkbox selection on
    the upload screen. Omit it to invite every still-pending candidate on the batch.
    """
    invitations = []
    candidates = batch.candidate_set.filter(
        status=Candidate.Status.PENDING_INVITE,
        validation_status=Candidate.ValidationStatus.OK,
        is_deleted=False,
    )
    if candidate_ids is not None:
        candidates = candidates.filter(candidate_id__in=candidate_ids)
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


def create_single_reinvite(candidate, user):
    """Issue one fresh Invitation for a candidate who's already been invited before
    (e.g. "Send Invite Again" from All Candidates / Candidate Details). Unlike
    create_invitations, this doesn't touch candidate.status - a re-invite doesn't change
    where the candidate is in the pipeline, it just gives them a new link/token.
    """
    return Invitation.objects.create(
        candidate=candidate,
        batch=candidate.batch,
        unique_link_token=_generate_token(),
        link_expired_at=candidate.batch.link_valid_until,
        is_re_invite=True,
        sent_by=user,
    )


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
                except EMAIL_SEND_ERRORS:
                    logger.exception(
                        'Failed to send invite email for invitation_id=%s', invitation.invitation_id
                    )
                    invitation.email_status = Invitation.EmailStatus.FAILED
                    invitation.save(update_fields=['email_status'])
        finally:
            connections.close_all()

    threading.Thread(target=_worker, daemon=True).start()


def partition_by_deliverable(candidates):
    """Split into (sendable, skipped) on whether there's an address to send to.

    Django's send_mail accepts a blank recipient and returns success without raising, so a
    candidate with no email produces no exception, no FAILED status, and a UI that cheerfully
    reports "sent" - the failure is completely invisible. Callers filter with this first and
    report the skipped ones back explicitly.
    """
    sendable, skipped = [], []
    for candidate in candidates:
        (sendable if (candidate.email or '').strip() else skipped).append(candidate)
    return sendable, skipped


def send_notification_emails(candidates, subject, body_for):
    """Send a notification (e.g. 'On Hold', 'Shortlisted', 'Not Selected') to a shortlist of
    candidates, on a single background thread - same fire-and-forget pattern as
    send_invites_async, since these emails don't have a per-row status to track back.

    `body_for` is a callable taking a candidate and returning that candidate's message body,
    so approved templates can personalise per recipient while a custom message stays constant.
    """
    def _worker():
        try:
            for candidate in candidates:
                try:
                    send_mail(
                        subject=subject,
                        message=body_for(candidate),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[candidate.email],
                        fail_silently=False,
                    )
                except EMAIL_SEND_ERRORS:
                    logger.exception(
                        'Failed to send notification email to candidate_id=%s', candidate.candidate_id
                    )
        finally:
            connections.close_all()

    threading.Thread(target=_worker, daemon=True).start()
