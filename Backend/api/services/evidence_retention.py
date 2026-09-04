"""Deletes proctoring evidence (ID/face photos and the session recording) once it is old enough
that it no longer needs to be kept.

Only the blobs and the three URL columns are cleared - the ExamAttempt row itself, its answers
and its scores stay exactly as they are. Deleting the row would erase a real result; deleting the
evidence is a separate, narrower policy.

Driven by started_at rather than a dedicated created_at column - that's when identity capture and
the recording actually began, so it is the closest real timestamp to when this evidence was
produced. An attempt with no started_at was never begun, so it never captured anything either.
"""

import os

from django.db.models import Q
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


def expired_evidence_queryset(now=None):
    now = now or timezone.now()
    cutoff = now - timezone.timedelta(days=RETENTION_DAYS)
    has_any_evidence = Q()
    for field in EVIDENCE_FIELDS:
        has_any_evidence |= Q(**{f'{field}__isnull': False})
    return ExamAttempt.objects.filter(has_any_evidence, started_at__lt=cutoff)


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
