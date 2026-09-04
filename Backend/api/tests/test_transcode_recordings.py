"""manage.py transcode_recordings - the query/claim/retry-limit orchestration around
services.video_transcode. Mocks video_transcode.transcode_to_mp4 itself (see
test_video_transcode.py for the real ffmpeg behaviour) since these tests are about which rows
get picked up and how retries/concurrency are handled, not about conversion correctness.
"""
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from api.management.commands.transcode_recordings import Command, MAX_TRANSCODE_ATTEMPTS
from api.models import ExamAttempt
from api.services import exam_session

pytestmark = pytest.mark.django_db


def _invitation(ta_user, make_batch, make_candidate, make_invitation):
    batch = make_batch(
        ta_user, link_valid_from=timezone.now() - timedelta(days=1),
        link_valid_until=timezone.now() + timedelta(days=2),
        logical_questions=0, quantitative_questions=0,
        verbal_questions=0, programming_questions=0,
    )
    candidate = make_candidate(batch, ta_user)
    return make_invitation(candidate, ta_user, link_expired_at=timezone.now() + timedelta(days=3))


def _finished_attempt(
    ta_user, make_batch, make_candidate, make_invitation,
    status=ExamAttempt.Status.SUBMITTED, has_recording=True, mp4_url=None, attempts=0,
):
    invitation = _invitation(ta_user, make_batch, make_candidate, make_invitation)
    attempt = ExamAttempt.objects.create(
        candidate=invitation.candidate, invitation=invitation, status=status,
        session_recording_url=(
            'https://example.test/attempts/1/session_recording.webm' if has_recording else None
        ),
        session_recording_mp4_url=mp4_url, mp4_transcode_attempts=attempts,
    )
    return attempt


class TestOnlyConvertsFinishedAttemptsWithARecording:
    def test_a_submitted_attempt_with_a_recording_is_converted(
        self, ta_user, make_batch, make_candidate, make_invitation, monkeypatch
    ):
        attempt = _finished_attempt(ta_user, make_batch, make_candidate, make_invitation)
        monkeypatch.setattr(
            'api.management.commands.transcode_recordings.video_transcode.transcode_to_mp4',
            lambda attempt_id: 'https://example.test/converted.mp4',
        )

        call_command('transcode_recordings')

        attempt.refresh_from_db()
        assert attempt.session_recording_mp4_url == 'https://example.test/converted.mp4'
        assert attempt.mp4_transcode_attempts == 1

    def test_an_in_progress_attempt_is_left_alone(
        self, ta_user, make_batch, make_candidate, make_invitation, monkeypatch
    ):
        """The WebM is still being appended to until the attempt is finalized - converting it
        mid-exam would race a chunk upload or fail on a partial file.
        """
        attempt = _finished_attempt(
            ta_user, make_batch, make_candidate, make_invitation,
            status=ExamAttempt.Status.IN_PROGRESS,
        )
        called = []
        monkeypatch.setattr(
            'api.management.commands.transcode_recordings.video_transcode.transcode_to_mp4',
            lambda attempt_id: called.append(attempt_id) or 'x',
        )

        call_command('transcode_recordings')

        assert called == []
        attempt.refresh_from_db()
        assert attempt.session_recording_mp4_url is None

    def test_an_attempt_with_no_recording_is_skipped(
        self, ta_user, make_batch, make_candidate, make_invitation, monkeypatch
    ):
        attempt = _finished_attempt(
            ta_user, make_batch, make_candidate, make_invitation, has_recording=False,
        )
        called = []
        monkeypatch.setattr(
            'api.management.commands.transcode_recordings.video_transcode.transcode_to_mp4',
            lambda attempt_id: called.append(attempt_id) or 'x',
        )

        call_command('transcode_recordings')

        assert called == []

    def test_an_already_converted_attempt_is_left_alone(
        self, ta_user, make_batch, make_candidate, make_invitation, monkeypatch
    ):
        attempt = _finished_attempt(
            ta_user, make_batch, make_candidate, make_invitation,
            mp4_url='https://example.test/already-done.mp4',
        )
        called = []
        monkeypatch.setattr(
            'api.management.commands.transcode_recordings.video_transcode.transcode_to_mp4',
            lambda attempt_id: called.append(attempt_id) or 'x',
        )

        call_command('transcode_recordings')

        assert called == []
        attempt.refresh_from_db()
        assert attempt.session_recording_mp4_url == 'https://example.test/already-done.mp4'

    def test_a_terminated_attempt_with_a_recording_is_also_converted(
        self, ta_user, make_batch, make_candidate, make_invitation, monkeypatch
    ):
        attempt = _finished_attempt(
            ta_user, make_batch, make_candidate, make_invitation,
            status=ExamAttempt.Status.TERMINATED,
        )
        monkeypatch.setattr(
            'api.management.commands.transcode_recordings.video_transcode.transcode_to_mp4',
            lambda attempt_id: 'https://example.test/converted.mp4',
        )

        call_command('transcode_recordings')

        attempt.refresh_from_db()
        assert attempt.session_recording_mp4_url == 'https://example.test/converted.mp4'


class TestFailuresAreCappedNotRetriedForever:
    def test_a_failed_conversion_increments_the_attempt_counter(
        self, ta_user, make_batch, make_candidate, make_invitation, monkeypatch
    ):
        attempt = _finished_attempt(ta_user, make_batch, make_candidate, make_invitation)
        monkeypatch.setattr(
            'api.management.commands.transcode_recordings.video_transcode.transcode_to_mp4',
            lambda attempt_id: None,
        )

        call_command('transcode_recordings')

        attempt.refresh_from_db()
        assert attempt.session_recording_mp4_url is None
        assert attempt.mp4_transcode_attempts == 1

    def test_a_recording_at_the_retry_limit_is_no_longer_attempted(
        self, ta_user, make_batch, make_candidate, make_invitation, monkeypatch
    ):
        attempt = _finished_attempt(
            ta_user, make_batch, make_candidate, make_invitation,
            attempts=MAX_TRANSCODE_ATTEMPTS,
        )
        called = []
        monkeypatch.setattr(
            'api.management.commands.transcode_recordings.video_transcode.transcode_to_mp4',
            lambda attempt_id: called.append(attempt_id) or 'x',
        )

        call_command('transcode_recordings')

        assert called == []
        attempt.refresh_from_db()
        assert attempt.mp4_transcode_attempts == MAX_TRANSCODE_ATTEMPTS

    def test_a_recording_just_under_the_limit_is_still_attempted(
        self, ta_user, make_batch, make_candidate, make_invitation, monkeypatch
    ):
        attempt = _finished_attempt(
            ta_user, make_batch, make_candidate, make_invitation,
            attempts=MAX_TRANSCODE_ATTEMPTS - 1,
        )
        monkeypatch.setattr(
            'api.management.commands.transcode_recordings.video_transcode.transcode_to_mp4',
            lambda attempt_id: 'https://example.test/converted.mp4',
        )

        call_command('transcode_recordings')

        attempt.refresh_from_db()
        assert attempt.session_recording_mp4_url == 'https://example.test/converted.mp4'
        assert attempt.mp4_transcode_attempts == MAX_TRANSCODE_ATTEMPTS


class TestDryRun:
    def test_dry_run_reports_without_converting_anything(
        self, ta_user, make_batch, make_candidate, make_invitation, monkeypatch
    ):
        attempt = _finished_attempt(ta_user, make_batch, make_candidate, make_invitation)
        called = []
        monkeypatch.setattr(
            'api.management.commands.transcode_recordings.video_transcode.transcode_to_mp4',
            lambda attempt_id: called.append(attempt_id) or 'x',
        )

        call_command('transcode_recordings', dry_run=True)

        assert called == []
        attempt.refresh_from_db()
        assert attempt.session_recording_mp4_url is None
        assert attempt.mp4_transcode_attempts == 0


class TestMaxPerRun:
    def test_max_bounds_how_many_are_attempted_in_one_run(
        self, ta_user, make_batch, make_candidate, make_invitation, monkeypatch
    ):
        for _ in range(3):
            _finished_attempt(ta_user, make_batch, make_candidate, make_invitation)
        calls = []
        monkeypatch.setattr(
            'api.management.commands.transcode_recordings.video_transcode.transcode_to_mp4',
            lambda attempt_id: calls.append(attempt_id) or 'https://example.test/x.mp4',
        )

        call_command('transcode_recordings', max_per_run=2)

        assert len(calls) == 2


class TestConcurrentRunsDoNotDoubleConvert:
    def test_a_row_already_claimed_by_a_concurrent_run_is_skipped(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        """Simulates a second scheduler instance having already claimed (incremented the
        attempt counter on) this row between this run reading it and reaching it - _claim_one_locked
        re-checks eligibility itself rather than trusting the earlier, unlocked read.
        """
        attempt = _finished_attempt(ta_user, make_batch, make_candidate, make_invitation)
        ExamAttempt.objects.filter(pk=attempt.pk).update(
            session_recording_mp4_url='https://example.test/beat-you-to-it.mp4',
        )

        claimed = Command()._claim_one_locked(attempt.pk)

        assert claimed is False
