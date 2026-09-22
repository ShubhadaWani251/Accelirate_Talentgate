"""Deletes proctoring evidence (ID/face photos and the session recording) once it is old enough
that it no longer needs to be kept.

Only the blobs and the three URL columns are cleared - the ExamAttempt row itself, its answers
and its scores stay exactly as they are. Deleting the row would erase a real result; deleting the
evidence is a separate, narrower policy.

Anchored on started_at where there is one - that's when identity capture and the recording
actually began, so it is the closest real timestamp to when this evidence was produced.

This used to be `started_at__lt=cutoff` alone, on the reasoning that an attempt with no
started_at was never begun and so never captured anything. That is not true, and the live data
says so: identity capture creates the attempt row and uploads the Aadhaar photo BEFORE the exam
starts, so a candidate who captures their card and then abandons the flow leaves a row with a
photo and a null started_at. Those rows matched nothing and their photographs were kept
indefinitely - the exact opposite of what a retention policy is for. AGE_ANCHOR falls back
through the remaining lifecycle timestamps and finally to the invitation's own created_at.

Invitation.created_at is nullable in the schema (it was added without a data migration), so
AGE_ANCHOR can in principle still be null - every invitation row in the database has one
today, and auto_now_add fills it on every insert, but the type does not guarantee it. A row
with no anchor at all is simply not purged, which keeps evidence rather than deleting it on a
guess; that is the right way round for this to fail.

The fallback order runs earliest-signal-first among those that precede capture, then the later
ones: started_at and id_verified_at bracket capture closely, aadhaar_verified_at is capture
time itself, and submitted_at/terminated_at are strictly after it, so anchoring on them retains
evidence slightly LONGER than its true age - the safe direction. invitation.created_at is the
only anchor that predates capture, and it is last precisely because of that.
"""

import os

from django.db.models import Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from api.models import ExamAttempt
from api.services import blob_storage

# Overridable for testing/ops without a code change, same pattern as EVIDENCE_URL_TTL_MINUTES in
# blob_storage.py.
RETENTION_DAYS = int(os.environ.get('EVIDENCE_RETENTION_DAYS', '30'))

EVIDENCE_FIELDS = (
    'aadhaar_capture_url', 'face_photo_url', 'session_recording_url',
    'session_recording_mp4_url',
)

# See the module docstring for why each of these, and why in this order.
AGE_ANCHOR = Coalesce(
    'started_at', 'id_verified_at', 'aadhaar_verified_at',
    'submitted_at', 'terminated_at', 'invitation__created_at',
)


def expired_evidence_queryset(now=None):
    now = now or timezone.now()
    cutoff = now - timezone.timedelta(days=RETENTION_DAYS)
    has_any_evidence = Q()
    for field in EVIDENCE_FIELDS:
        has_any_evidence |= Q(**{f'{field}__isnull': False})
    return (
        ExamAttempt.objects
        .annotate(_evidence_age_anchor=AGE_ANCHOR)
        .filter(has_any_evidence, _evidence_age_anchor__lt=cutoff)
    )


def purge_expired_evidence(now=None):
    """Deletes blobs and clears the URL columns for every attempt whose evidence has passed
    retention. Safe to run repeatedly - an attempt with all four URLs already null simply
    doesn't match the queryset a second time.
    """
    attempts = list(expired_evidence_queryset(now))
    purged = 0
    for attempt in attempts:
        blob_storage.delete_attempt_evidence(attempt.attempt_id)
        attempt.aadhaar_capture_url = None
        attempt.face_photo_url = None
        attempt.session_recording_url = None
        attempt.session_recording_mp4_url = None
        attempt.save(update_fields=list(EVIDENCE_FIELDS))
        purged += 1
    return purged
