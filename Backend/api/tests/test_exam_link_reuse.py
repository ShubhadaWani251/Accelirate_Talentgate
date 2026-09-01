"""Reopening the assessment link after the exam has genuinely begun must end the attempt, not
resume it.

Reported: a candidate closed the tab after reading every question, could look up answers
elsewhere, then reopen the same link and find the timer and any already-marked answers exactly
as they'd left them - free time to cheat with no consequence. The two public re-entry points
(ExamTokenLandingView, ExamVerifyEmailView) are the only way back in once the original tab/
session is gone - an ordinary same-tab reload never touches either (see ExamAttemptPage's own
restoreAttemptToken, which resumes straight from GET /api/exam/session/) - so reaching them again
with the clock already running is itself the signal that the original session didn't survive.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from api.models import ExamAttempt, ProctoringEvent
from api.services import exam_session


def _started_attempt(ta_user, make_batch, make_candidate, make_invitation):
    batch = make_batch(
        ta_user, link_valid_from=timezone.now() - timedelta(minutes=10),
        link_valid_until=timezone.now() + timedelta(days=2),
        logical_questions=0, quantitative_questions=0,
        verbal_questions=0, programming_questions=0,
    )
    candidate = make_candidate(batch, ta_user)
    invitation = make_invitation(
        candidate, ta_user, link_expired_at=timezone.now() + timedelta(days=3),
    )
    attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')
    exam_session.begin_exam(attempt)
    return invitation, attempt


class TestTokenLandingEndsAReopenedInProgressAttempt:
    def test_a_started_attempt_is_terminated_not_resumed(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation
    ):
        invitation, attempt = _started_attempt(ta_user, make_batch, make_candidate, make_invitation)

        response = api_client.get(f'/api/exam/token/{invitation.unique_link_token}/')

        assert response.data == {'reason': 'completed'}
        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.TERMINATED
        assert attempt.termination_reason == exam_session.TerminationReason.LINK_REOPENED

    def test_it_is_logged_as_a_critical_proctoring_event(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation
    ):
        invitation, attempt = _started_attempt(ta_user, make_batch, make_candidate, make_invitation)

        api_client.get(f'/api/exam/token/{invitation.unique_link_token}/')

        event = ProctoringEvent.objects.get(attempt=attempt)
        assert event.event_type == exam_session.TerminationReason.LINK_REOPENED
        assert event.is_violation is True
        assert event.severity == ProctoringEvent.Severity.CRITICAL

    def test_an_attempt_that_has_not_yet_begun_still_resumes_normally(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation
    ):
        """Identity captured (an ExamAttempt row exists) but the candidate hasn't reached the
        exam page yet (started_at is still null) - reloading the landing page here is the
        ordinary, legitimate path and must not be touched by this guard.
        """
        batch = make_batch(
            ta_user, link_valid_from=timezone.now() - timedelta(minutes=10),
            link_valid_until=timezone.now() + timedelta(days=2),
            logical_questions=0, quantitative_questions=0,
            verbal_questions=0, programming_questions=0,
        )
        candidate = make_candidate(batch, ta_user)
        invitation = make_invitation(
            candidate, ta_user, link_expired_at=timezone.now() + timedelta(days=3),
        )
        attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')
        assert attempt.started_at is None

        response = api_client.get(f'/api/exam/token/{invitation.unique_link_token}/')

        assert response.data == {'reason': 'ok', 'resume': True}
        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.IN_PROGRESS


class TestVerifyEmailEndsAReopenedInProgressAttempt:
    def test_a_started_attempt_is_terminated_and_refused_not_resumed(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation
    ):
        invitation, attempt = _started_attempt(ta_user, make_batch, make_candidate, make_invitation)

        response = api_client.post(
            f'/api/exam/token/{invitation.unique_link_token}/verify-email/',
            {'email': invitation.candidate.email},
        )

        assert response.status_code == 400
        assert 'resume' not in response.data
        assert 'attempt_token' not in response.data
        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.TERMINATED
        assert attempt.termination_reason == exam_session.TerminationReason.LINK_REOPENED

    def test_an_attempt_that_has_not_yet_begun_still_resumes_normally(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation
    ):
        batch = make_batch(
            ta_user, link_valid_from=timezone.now() - timedelta(minutes=10),
            link_valid_until=timezone.now() + timedelta(days=2),
            logical_questions=0, quantitative_questions=0,
            verbal_questions=0, programming_questions=0,
        )
        candidate = make_candidate(batch, ta_user)
        invitation = make_invitation(
            candidate, ta_user, link_expired_at=timezone.now() + timedelta(days=3),
        )
        attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')

        response = api_client.post(
            f'/api/exam/token/{invitation.unique_link_token}/verify-email/',
            {'email': invitation.candidate.email},
        )

        assert response.status_code == 200
        assert response.data['resume'] is True
        assert 'attempt_token' in response.data
        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.IN_PROGRESS
