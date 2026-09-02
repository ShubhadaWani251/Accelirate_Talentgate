import logging
import re
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
    batch and flip their status to INVITED. This only QUEUES the email - actually sending it is
    management/commands/process_email_queue.py's job, on its own schedule - so status reflects
    "invite issued", not "email delivered" (see Invitation.email_status for the latter).

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


def create_single_reinvite(candidate, user, link_valid_from=None, link_valid_until=None):
    """Issue one fresh Invitation for a candidate who's already been invited before
    (e.g. "Send Invite Again" from All Candidates / Candidate Details). Unlike
    create_invitations, this doesn't touch candidate.status - a re-invite doesn't change
    where the candidate is in the pipeline, it just gives them a new link/token.

    link_valid_from/link_valid_until: optional override for THIS invitation's own window,
    independent of the batch's - which is locked to its original dates once the batch leaves
    Draft (views/batches.py's EDITABLE_AFTER_DRAFT), specifically so re-inviting one straggler
    can't shift the window out from under every other candidate in the same batch. Omit either
    to inherit the batch's current value, same as before these parameters existed.

    Raises BatchNotInvitableError if the candidate's batch is Draft or Cancelled.
    """
    assert_batch_can_invite(candidate.batch)
    return Invitation.objects.create(
        candidate=candidate,
        batch=candidate.batch,
        unique_link_token=_generate_token(),
        link_valid_from=link_valid_from,
        link_expired_at=link_valid_until or candidate.batch.link_valid_until,
        is_re_invite=True,
        sent_by=user,
    )



def summarize_send_error(exc):
    """A short, human-readable reason for a failed send, safe to show a TA.

    Email-service errors arrive as multi-line dumps with the full request and response
    embedded. The useful sentence is usually the API's own "message" field, so that is pulled
    out when present; otherwise the first line is used. Truncated, because this is rendered in
    a table cell and the full traceback is in the application log either way.

    Deliberately does NOT include the raw response body wholesale: it can carry the API key
    header back in a request echo, and this value is served to the browser.
    """
    text = str(exc) or exc.__class__.__name__
    match = re.search(r'"message"\s*:\s*"([^"]+)"', text)
    if match:
        detail = match.group(1)
    else:
        detail = next((line.strip() for line in text.splitlines() if line.strip()), text)
    detail = ' '.join(detail.split())
    if len(detail) > 300:
        detail = detail[:297] + '...'
    return f'{exc.__class__.__name__}: {detail}'


def send_candidate_email(subject, body, to_address, cta_url=None,
                        cta_label='Start Your Assessment'):
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
    message.attach_alternative(
        text_body_to_html(body, cta_url=cta_url, cta_label=cta_label), 'text/html',
    )
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
    subject, body = render_invitation_email(candidate, invitation.batch, link, invitation.sent_by)
    # cta_url turns the assessment link into a real button in the HTML part; the bare URL
    # is still printed beneath it and in the plain-text part.
    send_candidate_email(subject, body, candidate.email, cta_url=link,
                        cta_label='Start Your Assessment')


def send_invite_and_record(invitation, base_url):
    """Send one invitation email and record the outcome on the row. Returns True if it sent.

    The single place an invitation's email_status is written. Its only caller is
    management/commands/process_email_queue.py - creating an Invitation (create_invitations /
    create_single_reinvite) only queues it (email_status=QUEUED); nothing sends inline from the
    request that created it. See that command's module docstring for why.

    Never raises: the outcome is the return value plus the row's own state. A caller looping
    over many invitations must not have the remainder abandoned because one address was bad.
    """
    attempted_at = timezone.now()
    try:
        send_invite_email(invitation, base_url)
    except EMAIL_SEND_ERRORS as exc:
        # Recorded on the row, not just in the log. A FAILED status with no reason attached is
        # close to useless - "unverified sender", "invalid address" and "timeout" need three
        # different fixes, and only the message distinguishes them. Still logged too, with the
        # traceback, for anything the summary loses.
        logger.exception(
            'Failed to send invite email for invitation_id=%s', invitation.invitation_id
        )
        invitation.email_status = Invitation.EmailStatus.FAILED
        invitation.email_error = summarize_send_error(exc)
        invitation.email_last_attempt_at = attempted_at
        invitation.save(update_fields=[
            'email_status', 'email_error', 'email_last_attempt_at',
        ])
        return False
    except Exception as exc:
        # A failure OUTSIDE the email backend's own exception family - a bug in rendering, a
        # database error mid-loop. Previously this escaped the loop and every remaining
        # invitation was silently left QUEUED, reading as "in progress" forever. Record it and
        # let the caller carry on with the rest.
        logger.exception(
            'Unexpected error sending invite for invitation_id=%s', invitation.invitation_id,
        )
        invitation.email_status = Invitation.EmailStatus.FAILED
        invitation.email_error = summarize_send_error(exc)
        invitation.email_last_attempt_at = attempted_at
        invitation.save(update_fields=[
            'email_status', 'email_error', 'email_last_attempt_at',
        ])
        return False

    invitation.email_status = Invitation.EmailStatus.SENT
    invitation.email_sent_at = attempted_at
    invitation.email_last_attempt_at = attempted_at
    # Cleared, so a reason from an earlier failed attempt can't sit next to a SENT status and
    # be read as current.
    invitation.email_error = None
    invitation.save(update_fields=[
        'email_status', 'email_sent_at', 'email_last_attempt_at', 'email_error',
    ])
    return True


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
    candidates, on a single background thread - fire-and-forget, since these emails don't have a
    per-row status to track back the way an Invitation does. Unlike invitation emails (see
    management/commands/process_email_queue.py), these stay on the inline thread: a TA-triggered
    notification is typically a small, deliberate shortlist, not the 100+-candidate blast that
    made a durable queue worth the complexity for invitations specifically.

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
