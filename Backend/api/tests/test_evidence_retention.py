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
