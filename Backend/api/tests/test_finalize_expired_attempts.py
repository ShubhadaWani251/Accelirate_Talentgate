"""manage.py finalize_expired_attempts - the safety net for exam attempts nobody ever revisits,
plus the concurrency-safety property that makes it safe to run from more than one App Service
instance at once (a prerequisite for scaling the web tier out without touching this code again -
see the command's own module docstring).
"""
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from api.management.commands.finalize_expired_attempts import Command
from api.models import ExamAttempt
from api.services import exam_session

pytestmark = pytest.mark.django_db


def _invitation(ta_user, make_batch, make_candidate, make_invitation, **kwargs):
    batch = make_batch(
        ta_user, link_valid_from=timezone.now() - timedelta(days=1),
        link_valid_until=timezone.now() + timedelta(days=2),
        logical_questions=0, quantitative_questions=0,
        verbal_questions=0, programming_questions=0,
    )
    candidate = make_candidate(batch, ta_user)
    defaults = {'link_expired_at': timezone.now() + timedelta(days=3)}
    defaults.update(kwargs)
    return make_invitation(candidate, ta_user, **defaults)


class TestFinalizesTimedOutAndAbandonedAttempts:
    def test_an_attempt_past_its_deadline_is_finalized(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        invitation = _invitation(ta_user, make_batch, make_candidate, make_invitation)
        attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')
        exam_session.begin_exam(attempt)
        ExamAttempt.objects.filter(pk=attempt.pk).update(
            started_at=timezone.now() - timedelta(hours=1),
        )

        call_command('finalize_expired_attempts')

        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.SUBMITTED

    def test_an_attempt_still_within_its_deadline_is_left_alone(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        invitation = _invitation(ta_user, make_batch, make_candidate, make_invitation)
        attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')
        exam_session.begin_exam(attempt)

        call_command('finalize_expired_attempts')

        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.IN_PROGRESS

    def test_a_never_begun_attempt_is_finalized_once_its_link_expires(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        invitation = _invitation(
            ta_user, make_batch, make_candidate, make_invitation,
            link_expired_at=timezone.now() - timedelta(hours=1),
        )
        attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')
        assert attempt.started_at is None

        call_command('finalize_expired_attempts')

        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.SUBMITTED

    def test_a_never_begun_attempt_with_a_still_valid_link_is_left_alone(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        invitation = _invitation(ta_user, make_batch, make_candidate, make_invitation)
        attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')

        call_command('finalize_expired_attempts')

        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.IN_PROGRESS


class TestConcurrentRunsDoNotRace:
    def test_an_attempt_already_finalized_by_a_concurrent_run_is_skipped(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        invitation = _invitation(ta_user, make_batch, make_candidate, make_invitation)
        attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')
        exam_session.begin_exam(attempt)
        ExamAttempt.objects.filter(pk=attempt.pk).update(
            started_at=timezone.now() - timedelta(hours=1),
        )
        # Simulates a concurrent run (a second App Service instance) having already finalized
        # this exact row in the gap between this command reading it and reaching it.
        exam_session.finalize_attempt(attempt, outcome='submitted')
        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.SUBMITTED
        submitted_at_before = attempt.submitted_at

        outcome = Command()._finalize_one_locked(attempt.pk, timezone.now())

        assert outcome is None
        attempt.refresh_from_db()
        assert attempt.submitted_at == submitted_at_before
