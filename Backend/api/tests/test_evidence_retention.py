"""services/evidence_retention.py - the 30-day evidence purge sweep, specifically covering
session_recording_mp4_url now that it exists: it must be picked up by the "has any evidence"
queryset AND actually cleared (not just matched) by the purge itself, since a field added to
EVIDENCE_FIELDS but not to the explicit None-assignments in purge_expired_evidence would match
the query forever without ever being cleared - the exact bug self-caught while wiring this up.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from api.models import ExamAttempt
from api.services import blob_storage, evidence_retention

pytestmark = pytest.mark.django_db


def _old_attempt(ta_user, make_batch, make_candidate, make_invitation, **fields):
    batch = make_batch(ta_user)
    candidate = make_candidate(batch, ta_user)
    invitation = make_invitation(candidate, ta_user)
    attempt = ExamAttempt.objects.create(
        candidate=candidate, invitation=invitation, status=ExamAttempt.Status.SUBMITTED,
        started_at=timezone.now() - timedelta(days=evidence_retention.RETENTION_DAYS + 1),
        **fields,
    )
    return attempt


class TestMp4UrlIsIncludedInRetention:
    def test_an_attempt_with_only_an_mp4_url_is_matched_by_the_expired_queryset(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        attempt = _old_attempt(
            ta_user, make_batch, make_candidate, make_invitation,
            session_recording_mp4_url='https://example.test/recording.mp4',
        )

        assert attempt in evidence_retention.expired_evidence_queryset()

    def test_purge_actually_clears_the_mp4_url_not_just_matches_it(
        self, ta_user, make_batch, make_candidate, make_invitation, settings
    ):
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        attempt = _old_attempt(
            ta_user, make_batch, make_candidate, make_invitation,
            session_recording_url='https://example.test/recording.webm',
            session_recording_mp4_url='https://example.test/recording.mp4',
        )

        purged = evidence_retention.purge_expired_evidence()

        assert purged == 1
        attempt.refresh_from_db()
        assert attempt.session_recording_url is None
        assert attempt.session_recording_mp4_url is None

    def test_the_mp4_blob_is_actually_deleted_alongside_the_webm(
        self, ta_user, make_batch, make_candidate, make_invitation, settings
    ):
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        attempt = _old_attempt(
            ta_user, make_batch, make_candidate, make_invitation,
        )
        blob_storage.start_recording_blob(attempt.attempt_id)
        blob_storage.append_recording_chunk(attempt.attempt_id, b'webm-bytes')
        mp4_path = blob_storage._local_path(attempt.attempt_id, 'session_recording.mp4')
        mp4_path.write_bytes(b'mp4-bytes')
        ExamAttempt.objects.filter(pk=attempt.pk).update(
            session_recording_url='https://example.test/recording.webm',
            session_recording_mp4_url='https://example.test/recording.mp4',
        )
        assert mp4_path.exists()

        evidence_retention.purge_expired_evidence()

        assert not mp4_path.exists()


class TestEvidenceWithNoStartedAtIsStillPurged:
    """The retention sweep used to filter on started_at alone, so evidence from an attempt that
    never began was kept forever.

    That is not a hypothetical shape: identity capture creates the attempt row and uploads the
    Aadhaar photo BEFORE the exam starts, so abandoning the flow at that point leaves a row
    holding a photograph of someone's Aadhaar card and no started_at at all. 18 such rows were
    found in the live database while auditing this.
    """

    def _abandoned_capture(self, ta_user, make_batch, make_candidate, make_invitation,
                           age_days, **fields):
        """An attempt holding an Aadhaar photo with no started_at, dated only by its invitation."""
        batch = make_batch(ta_user)
        candidate = make_candidate(batch, ta_user)
        invitation = make_invitation(
            candidate, ta_user, created_at=timezone.now() - timedelta(days=age_days),
        )
        return ExamAttempt.objects.create(
            candidate=candidate, invitation=invitation,
            started_at=None,
            aadhaar_capture_url='https://example.test/id_photo.jpg',
            **fields,
        )

    def test_an_abandoned_aadhaar_capture_is_matched_once_it_is_old_enough(
        self, ta_user, make_batch, make_candidate, make_invitation,
    ):
        attempt = self._abandoned_capture(
            ta_user, make_batch, make_candidate, make_invitation,
            age_days=evidence_retention.RETENTION_DAYS + 1,
        )

        assert attempt in evidence_retention.expired_evidence_queryset()

    def test_a_recent_abandoned_capture_is_left_alone(
        self, ta_user, make_batch, make_candidate, make_invitation,
    ):
        attempt = self._abandoned_capture(
            ta_user, make_batch, make_candidate, make_invitation, age_days=1,
        )

        assert attempt not in evidence_retention.expired_evidence_queryset()

    def test_the_photo_url_is_actually_cleared_not_just_matched(
        self, ta_user, make_batch, make_candidate, make_invitation, settings,
    ):
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        attempt = self._abandoned_capture(
            ta_user, make_batch, make_candidate, make_invitation,
            age_days=evidence_retention.RETENTION_DAYS + 1,
        )

        assert evidence_retention.purge_expired_evidence() == 1
        attempt.refresh_from_db()
        assert attempt.aadhaar_capture_url is None

    def test_a_later_lifecycle_timestamp_anchors_the_age_when_started_at_is_null(
        self, ta_user, make_batch, make_candidate, make_invitation,
    ):
        """submitted_at outranks the invitation date, and it is LATER - so a row whose
        invitation is ancient but which was submitted yesterday must be retained, not purged.
        Anchoring on the invitation instead would delete evidence well before its time.
        """
        attempt = self._abandoned_capture(
            ta_user, make_batch, make_candidate, make_invitation,
            age_days=evidence_retention.RETENTION_DAYS + 10,
            status=ExamAttempt.Status.SUBMITTED,
            submitted_at=timezone.now() - timedelta(days=1),
        )

        assert attempt not in evidence_retention.expired_evidence_queryset()

    def test_an_attempt_with_no_evidence_at_all_is_never_matched(
        self, ta_user, make_batch, make_candidate, make_invitation,
    ):
        """The anchor fallback widened which rows have an age; it must not widen which rows are
        considered to hold evidence.
        """
        batch = make_batch(ta_user)
        candidate = make_candidate(batch, ta_user)
        invitation = make_invitation(
            candidate, ta_user,
            created_at=timezone.now() - timedelta(days=evidence_retention.RETENTION_DAYS + 1),
        )
        attempt = ExamAttempt.objects.create(
            candidate=candidate, invitation=invitation, started_at=None,
        )

        assert attempt not in evidence_retention.expired_evidence_queryset()
