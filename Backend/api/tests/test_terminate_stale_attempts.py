"""manage.py terminate_stale_attempts - catches a candidate's browser/Safe Exam Browser closing
mid-exam, distinct from finalize_expired_attempts (which owns an attempt that simply ran out of
time) - see the command's own module docstring for why staleness, not an unload event, is what
this watches.
"""
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from api.models import ExamAttempt
from api.services import exam_session
from api.services.exam_session import TerminationReason

pytestmark = pytest.mark.django_db


def _invitation(ta_user, make_batch, make_candidate, make_invitation, **kwargs):
    batch = make_batch(
        ta_user, link_valid_from=timezone.now() - timedelta(days=1),
        link_valid_until=timezone.now() + timedelta(days=2),
        logical_questions=0, quantitative_questions=0,
        verbal_questions=0, programming_questions=0,
        exam_duration_minutes=45,
    )
    candidate = make_candidate(batch, ta_user)
    defaults = {'link_expired_at': timezone.now() + timedelta(days=3)}
    defaults.update(kwargs)
    return make_invitation(candidate, ta_user, **defaults)


def _begun_attempt(ta_user, make_batch, make_candidate, make_invitation, last_activity_ago):
    """A started, in-progress attempt whose last_activity_at is `last_activity_ago` in the past -
    well within its own exam_duration_minutes unless the caller overrides that separately.
    """
    invitation = _invitation(ta_user, make_batch, make_candidate, make_invitation)
    attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')
    exam_session.begin_exam(attempt)
    ExamAttempt.objects.filter(pk=attempt.pk).update(
        last_activity_at=timezone.now() - last_activity_ago,
    )
    attempt.refresh_from_db()
    return attempt


class TestTerminatesGenuinelyStaleAttempts:
    def test_an_attempt_silent_past_the_threshold_is_terminated(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        attempt = _begun_attempt(
            ta_user, make_batch, make_candidate, make_invitation,
            last_activity_ago=timedelta(seconds=90),
        )

        call_command('terminate_stale_attempts', threshold_seconds=60)

        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.TERMINATED
        assert attempt.termination_reason == TerminationReason.WINDOW_CLOSED

    def test_it_is_recorded_as_a_violation_not_a_warning(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        from api.models import ProctoringEvent

        attempt = _begun_attempt(
            ta_user, make_batch, make_candidate, make_invitation,
            last_activity_ago=timedelta(seconds=90),
        )

        call_command('terminate_stale_attempts', threshold_seconds=60)

        event = ProctoringEvent.objects.get(attempt=attempt)
        assert event.event_type == TerminationReason.WINDOW_CLOSED
        assert event.is_violation is True
        assert event.severity == ProctoringEvent.Severity.CRITICAL

    def test_a_recently_active_attempt_is_left_alone(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        attempt = _begun_attempt(
            ta_user, make_batch, make_candidate, make_invitation,
            last_activity_ago=timedelta(seconds=15),
        )

        call_command('terminate_stale_attempts', threshold_seconds=60)

        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.IN_PROGRESS

    def test_an_attempt_with_no_activity_timestamp_at_all_is_left_alone(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        """last_activity_at is only ever set by CandidateAttemptAuthentication - an attempt that
        was start_or_resume_attempt'd directly (as every fixture here does, bypassing real HTTP)
        never got a single authenticated request, so it is null, not stale. The query filters on
        `__lt=cutoff`, which a null value never matches - confirms that exclusion explicitly
        rather than trusting the ORM's NULL semantics silently.
        """
        invitation = _invitation(ta_user, make_batch, make_candidate, make_invitation)
        attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')
        exam_session.begin_exam(attempt)
        assert attempt.last_activity_at is None

        call_command('terminate_stale_attempts', threshold_seconds=60)

        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.IN_PROGRESS

    def test_an_attempt_that_has_not_begun_is_left_alone_regardless_of_staleness(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        invitation = _invitation(ta_user, make_batch, make_candidate, make_invitation)
        attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')
        ExamAttempt.objects.filter(pk=attempt.pk).update(
            last_activity_at=timezone.now() - timedelta(hours=1),
        )
        assert attempt.started_at is None

        call_command('terminate_stale_attempts', threshold_seconds=60)

        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.IN_PROGRESS


class TestDefersToFinalizeExpiredAttemptsForAGenuineTimeout:
    def test_an_attempt_both_stale_and_past_its_own_deadline_is_left_for_the_other_command(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        attempt = _begun_attempt(
            ta_user, make_batch, make_candidate, make_invitation,
            last_activity_ago=timedelta(seconds=90),
        )
        # Past its own exam_duration_minutes (45, from _invitation's batch) as well as stale.
        ExamAttempt.objects.filter(pk=attempt.pk).update(
            started_at=timezone.now() - timedelta(hours=1),
        )

        call_command('terminate_stale_attempts', threshold_seconds=60)

        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.IN_PROGRESS
        assert attempt.termination_reason is None


class TestDryRun:
    def test_dry_run_reports_without_changing_anything(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        attempt = _begun_attempt(
            ta_user, make_batch, make_candidate, make_invitation,
            last_activity_ago=timedelta(seconds=90),
        )

        call_command('terminate_stale_attempts', threshold_seconds=60, dry_run=True)

        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.IN_PROGRESS


class TestThresholdIsConfigurable:
    def test_a_shorter_threshold_catches_what_the_default_would_not_yet(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        attempt = _begun_attempt(
            ta_user, make_batch, make_candidate, make_invitation,
            last_activity_ago=timedelta(seconds=20),
        )

        call_command('terminate_stale_attempts', threshold_seconds=10)

        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.TERMINATED


class TestCandidateAttemptAuthenticationStampsTheHeartbeat:
    """The other half of this feature - without this, last_activity_at would never move and
    every attempt would look permanently stale the moment the threshold elapsed, regardless of
    whether the candidate's browser was actually still there.
    """

    def test_a_successful_authenticated_request_updates_last_activity_at(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation
    ):
        from api.services.tokens import issue_attempt_token

        invitation = _invitation(ta_user, make_batch, make_candidate, make_invitation)
        attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')
        assert attempt.last_activity_at is None

        api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {issue_attempt_token(attempt)}')
        response = api_client.get('/api/exam/session/')

        assert response.status_code == 200
        attempt.refresh_from_db()
        assert attempt.last_activity_at is not None
