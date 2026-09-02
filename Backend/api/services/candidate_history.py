"""Builds the chronological event list behind the "View History" action.

The upload-review screen's History button exists so a TA can see what happened to a candidate
*before* this upload - so history deliberately spans two records: the candidate row being
reviewed, plus whichever historical candidate row the CURRENT (most recent) Aadhaar+DOB
duplicate check matched. Each event carries the batch it belongs to, so a TA can tell "this
attempt was 5 months ago in BATCH-0098" from "this row was uploaded today".
"""

from api.models import AuditLog, Candidate, ExamAttempt, Invitation
from api.services.exam_session import termination_label

# Audit actions worth surfacing to a TA, mapped to human-readable labels. Anything not listed
# (internal bookkeeping, reads) is intentionally omitted rather than dumped raw into the modal.
# NB: 'invite_sent' is deliberately absent - invites are surfaced from the Invitation table
# above, which also knows whether delivery failed and whether it was a re-send. Listing it
# here too would double every invite row in the modal.
_AUDIT_EVENT_LABELS = {
    'update': 'Details Edited',
    'notify_sent': 'Notification Email Sent',
    'certification_sent': 'Certification Link Sent',
    'duplicate_cleared': 'Duplicate Flag Cleared',
}


def _event(timestamp, label, batch_name):
    return {'timestamp': timestamp, 'event': label, 'batch_name': batch_name}


def _attempt_events(attempt, batch_name):
    """One attempt can contribute up to two rows: when it started, and how it ended."""
    events = []
    if attempt.started_at:
        events.append(_event(attempt.started_at, 'Exam Started', batch_name))

    if attempt.status == ExamAttempt.Status.TERMINATED:
        events.append(_event(attempt.terminated_at or attempt.started_at,
                             f'Terminated - {termination_label(attempt.termination_reason)}',
                             batch_name))
    elif attempt.status == ExamAttempt.Status.SUBMITTED:
        score = f' ({attempt.overall_score})' if attempt.overall_score is not None else ''
        events.append(_event(attempt.submitted_at or attempt.started_at,
                             f'Completed{score}', batch_name))
    return events


def _events_for_record(candidate):
    """Every event belonging to one candidate row."""
    batch_name = candidate.batch.batch_name
    events = [_event(candidate.created_at, 'Uploaded', batch_name)]

    for invitation in Invitation.objects.filter(candidate=candidate).order_by('invitation_id'):
        label = 'Invite Re-sent' if invitation.is_re_invite else 'Invite Sent'
        if invitation.email_status == Invitation.EmailStatus.FAILED:
            label = f'{label} - delivery failed'
        # An invite that hasn't been dispatched yet has no email_sent_at; fall back to the
        # candidate's own timestamp so the row still appears in a sensible position.
        events.append(_event(invitation.email_sent_at or candidate.created_at, label, batch_name))

    for attempt in ExamAttempt.objects.filter(candidate=candidate).order_by('attempt_id'):
        events.extend(_attempt_events(attempt, batch_name))

    audit_rows = AuditLog.objects.filter(
        entity_type='candidate', entity_id=candidate.candidate_id,
        action_type__in=_AUDIT_EVENT_LABELS,
    ).order_by('created_at')
    for row in audit_rows:
        events.append(_event(row.created_at, _AUDIT_EVENT_LABELS[row.action_type], batch_name))

    return events


def build_candidate_history(candidate):
    """Chronological events for this candidate plus any historical record matched by the
    CURRENT (most recent) duplicate check. Returns oldest-first, which is how the wireframe's
    History modal reads (Uploaded -> Invite Sent -> Completed).

    Only the LATEST DuplicateCheck counts, not every one ever run for this row - a row can be
    edited (Aadhaar/DOB corrected on the Review step) after an earlier check matched it to
    someone, and run_duplicate_check always records a NEW check rather than updating the old
    one, so old rows accumulate. Following every one of them would keep showing a match the
    correction has since disproven - inconsistent with the duplicate-status pill on the same
    screen, which already only ever shows the latest verdict (see CandidateStagingSerializer.
    _latest_check). Same "pick the max by checked_at" pattern here, so History and the pill can
    never disagree.
    """
    records = [candidate]

    latest_check = max(
        candidate.duplicate_checks.all(), key=lambda check: check.checked_at, default=None,
    )
    if (latest_check and latest_check.existing_candidate_id
            and latest_check.existing_candidate_id != candidate.candidate_id):
        records.extend(
            Candidate.objects.select_related('batch')
            .filter(candidate_id=latest_check.existing_candidate_id)
        )

    events = []
    for record in records:
        events.extend(_events_for_record(record))

    # Newest first: the history panel is read to answer "what happened to this candidate
    # most recently", so the latest event belongs at the top rather than at the bottom of a
    # list the reader has to scroll through.
    #
    # Events with no usable timestamp would break sorting - they can't happen given the
    # fallbacks above, but sort defensively rather than risk a 500 on a null. Nulls stay last
    # in both directions, which is why the reverse is applied to the timestamp only and not by
    # passing reverse=True (that would float the nulls to the top).
    return sorted(
        events,
        key=lambda e: (e['timestamp'] is None, -(e['timestamp'].timestamp())
                       if e['timestamp'] else 0),
    )
