import logging
import secrets
import threading

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import connections
from django.utils import timezone

from api.models import Batch, Candidate, Invitation
from api.services.email_errors import EMAIL_SEND_ERRORS
from api.services.email_templates import render_invitation_email, text_body_to_html

logger = logging.getLogger(__name__)


class BatchNotInvitableError(Exception):
    """A batch's status forbids issuing invitations. Carries the message shown to the user."""


# Only a live batch may issue invitations. A Draft hasn't been activated yet, and a Cancelled
# batch is closed - both stay fully visible and readable, they just can't send.
INVITE_BLOCKED_REASONS = {
    Batch.Status.DRAFT: (
        'This batch is currently in Draft status. Candidates can be validated, but invitations '
        'cannot be sent until the batch is activated.'
    ),
    Batch.Status.CANCELLED: (
        'This batch has been cancelled. New candidates cannot be processed or invited for this '
        'batch.'
    ),
}


def assert_batch_can_invite(batch):
    """Raise BatchNotInvitableError if this batch's status forbids sending invitations.

    Enforced here rather than only in the views because this module is the single place
    Invitation rows are created. Per-view checks had already drifted once - the re-invite
    endpoint blocked Draft but not Cancelled, so a closed batch could still email a fresh
    assessment link. Guarding the choke point means a new caller cannot reintroduce that gap.
    """
    reason = INVITE_BLOCKED_REASONS.get(batch.status)
    if reason:
        raise BatchNotInvitableError(reason)


def _generate_token():
    return secrets.token_urlsafe(32)[:64]


def create_invitations(batch, user, candidate_ids=None):
    """Create one Invitation per eligible (OK-validated, still pending) candidate on this
    batch and flip their status to INVITED. Email sending itself is a separate, async step
    (see send_invites_async) - status reflects "invite issued", not "email delivered"
    (see Invitation.email_status for the latter).

    `candidate_ids` narrows this to an explicit subset - the reviewer's checkbox selection on
    the upload screen. Omit it to invite every still-pending candidate on the batch.

    Raises BatchNotInvitableError if the batch is Draft or Cancelled.
    """
    assert_batch_can_invite(batch)
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

    Raises BatchNotInvitableError if the candidate's batch is Draft or Cancelled.
    """
    assert_batch_can_invite(candidate.batch)
    return Invitation.objects.create(
        candidate=candidate,
        batch=candidate.batch,
        unique_link_token=_generate_token(),
        link_expired_at=candidate.batch.link_valid_until,
        is_re_invite=True,
        sent_by=user,
    )


def send_candidate_email(subject, body, to_address):
    """Send one candidate-facing email as multipart text + HTML.

    Single seam for every candidate email (invitation, notifications, certification) so they
    all behave the same way. The plain-text part is the approved copy unchanged; the HTML part
    is generated from it purely so URLs arrive clickable - candidates used to have to select
    the assessment link and paste it into a browser, because a bare URL in a plain-text mail
    is only auto-linked by some clients and Outlook frequently isn't one of them.

    A client that prefers text still gets the text part, so nothing is lost by adding this.
    services/graph_email.py already looks for a text/html alternative and flips the Graph
    payload's contentType accordingly, so no transport change is needed here.
    """
    message = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_address],
    )
    message.attach_alternative(text_body_to_html(body), 'text/html')
    # Matches the previous send_mail(fail_silently=False): callers rely on the exception to
    # mark an invitation FAILED rather than reporting a silent success.
    message.send(fail_silently=False)


def send_invite_email(invitation, base_url):
    """Send the approved invitation copy for one invitation.

    The wording lives in services/email_templates.py with the rest of the candidate-facing
    copy - it used to be inline here, which meant the one email candidates actually receive
    was the only one not covered by the approved-template registry.
    """
    candidate = invitation.candidate
    link = f"{base_url.rstrip('/')}/t/{invitation.unique_link_token}"
    subject, body = render_invitation_email(candidate, invitation.batch, link)
    send_candidate_email(subject, body, candidate.email)


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
                    # Same text+HTML treatment as the invitation: the certification email
                    # carries two UiPath Academy course URLs, which had the identical
                    # copy-and-paste problem.
                    send_candidate_email(subject, body_for(candidate), candidate.email)
                except EMAIL_SEND_ERRORS:
                    logger.exception(
                        'Failed to send notification email to candidate_id=%s', candidate.candidate_id
                    )
        finally:
            connections.close_all()

    threading.Thread(target=_worker, daemon=True).start()
