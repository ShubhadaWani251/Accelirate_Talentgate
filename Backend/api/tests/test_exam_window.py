"""A candidate must not be able to start (or even begin walking through) an exam before the
batch's own link_valid_from - reported live: a batch with tomorrow's date set as the start still
let a candidate begin the assessment today. Every earlier check in this file (the landing screen,
email verification, identity capture) only ever checked the link's EXPIRY (link_expired_at /
link_valid_until); nothing checked the START. begin_exam() is the authoritative fix - it is the
one function that actually starts the clock - with the earlier screens mirroring the same check
so a candidate sees a clear message before wasting a camera/mic permission prompt and photo
capture on a window that hasn't opened yet.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from api.services import exam_session
from api.services.tokens import issue_attempt_token


def _invitation(ta_user, make_batch, make_candidate, make_invitation, link_valid_from):
    # Zero questions per section: these tests exercise the window-timing gate, not question
    # selection, and no question bank is seeded here - see test_security.py's identical choice
    # for why 0 (not omitted) is what keeps select_questions_for_attempt a no-op instead of
    # raising InsufficientQuestionsError.
    batch = make_batch(
        ta_user, link_valid_from=link_valid_from,
        link_valid_until=link_valid_from + timedelta(days=2),
        logical_questions=0, quantitative_questions=0,
        verbal_questions=0, programming_questions=0,
    )
    candidate = make_candidate(batch, ta_user)
    return make_invitation(
        candidate, ta_user, link_expired_at=timezone.now() + timedelta(days=3),
    )


class TestBeginExamRefusesBeforeTheWindowOpens:
    """Unit-level: begin_exam() is the one function that actually starts the clock, so this is
    the authoritative gate - correct here regardless of how a candidate reached it.
    """

    def test_raises_when_the_window_has_not_opened(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        invitation = _invitation(
            ta_user, make_batch, make_candidate, make_invitation,
            link_valid_from=timezone.now() + timedelta(days=1),
        )
        attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')

        with pytest.raises(exam_session.ExamNotYetOpenError):
            exam_session.begin_exam(attempt)

        attempt.refresh_from_db()
        assert attempt.started_at is None

    def test_starts_the_clock_once_the_window_is_open(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        invitation = _invitation(
            ta_user, make_batch, make_candidate, make_invitation,
            link_valid_from=timezone.now() - timedelta(minutes=5),
        )
        attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')

        exam_session.begin_exam(attempt)

        attempt.refresh_from_db()
        assert attempt.started_at is not None

    def test_a_resumed_attempt_is_never_re_blocked(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        """Guards against a batch somehow reporting not-yet-open after an attempt already
        legitimately started - begin_exam must stay a no-op on the second call, never re-raise.
        """
        invitation = _invitation(
            ta_user, make_batch, make_candidate, make_invitation,
            link_valid_from=timezone.now() - timedelta(minutes=5),
        )
        attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')
        exam_session.begin_exam(attempt)
        first_started_at = attempt.started_at

        exam_session.begin_exam(attempt)  # idempotent re-hit, e.g. a page reload

        assert attempt.started_at == first_started_at


class TestExamTokenLandingRefusesBeforeTheWindowOpens:
    def test_reports_not_yet_open_with_no_attempt_yet(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation
    ):
        opens_at = timezone.now() + timedelta(days=1)
        invitation = _invitation(
            ta_user, make_batch, make_candidate, make_invitation, link_valid_from=opens_at,
        )

        response = api_client.get(f'/api/exam/token/{invitation.unique_link_token}/')

        assert response.status_code == 200
        assert response.data['reason'] == 'not_yet_open'
        assert response.data['opens_at'] == opens_at.isoformat()

    def test_reports_ok_once_the_window_is_open(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation
    ):
        invitation = _invitation(
            ta_user, make_batch, make_candidate, make_invitation,
            link_valid_from=timezone.now() - timedelta(minutes=5),
        )

        response = api_client.get(f'/api/exam/token/{invitation.unique_link_token}/')

        assert response.status_code == 200
        assert response.data['reason'] == 'ok'


class TestExamVerifyEmailRefusesBeforeTheWindowOpens:
    def test_a_fresh_start_is_rejected(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation
    ):
        opens_at = timezone.now() + timedelta(days=1)
        invitation = _invitation(
            ta_user, make_batch, make_candidate, make_invitation, link_valid_from=opens_at,
        )

        response = api_client.post(
            f'/api/exam/token/{invitation.unique_link_token}/verify-email/',
            {'email': invitation.candidate.email}, format='json',
        )

        assert response.status_code == 400
        assert response.data['opens_at'] == opens_at.isoformat()

    def test_a_matching_email_proceeds_once_the_window_is_open(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation
    ):
        invitation = _invitation(
            ta_user, make_batch, make_candidate, make_invitation,
            link_valid_from=timezone.now() - timedelta(minutes=5),
        )

        response = api_client.post(
            f'/api/exam/token/{invitation.unique_link_token}/verify-email/',
            {'email': invitation.candidate.email}, format='json',
        )

        assert response.status_code == 200
        assert response.data['resume'] is False


class TestExamIdentityCaptureRefusesBeforeTheWindowOpens:
    def _files(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        body = b'\xff\xd8\xff\xe0fake-jpeg-bytes'
        return {
            'id_photo': SimpleUploadedFile('id.jpg', body, content_type='image/jpeg'),
            'face_photo': SimpleUploadedFile('face.jpg', body, content_type='image/jpeg'),
        }

    def test_identity_capture_is_rejected(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation
    ):
        opens_at = timezone.now() + timedelta(days=1)
        invitation = _invitation(
            ta_user, make_batch, make_candidate, make_invitation, link_valid_from=opens_at,
        )

        response = api_client.post(
            f'/api/exam/token/{invitation.unique_link_token}/identity/',
            self._files(), format='multipart',
        )

        assert response.status_code == 400
        assert response.data['opens_at'] == opens_at.isoformat()
        # Confirms this is rejected before any attempt is ever created - not just rejected after
        # partially creating one.
        from api.models import ExamAttempt
        assert not ExamAttempt.objects.filter(invitation=invitation).exists()


class TestExamBeginViewRefusesBeforeTheWindowOpens:
    """API-level check on /api/exam/begin/ itself, authenticating as the attempt the same way a
    candidate's browser does (services.tokens.issue_attempt_token) - confirms the authoritative
    service-layer gate is actually wired through the view, not just correct in isolation.
    """

    def test_begin_is_rejected(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation, settings
    ):
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True  # local-disk fallback for the question bank being empty is fine -
        # begin_exam's window check runs before anything else uses the question set.
        opens_at = timezone.now() + timedelta(days=1)
        invitation = _invitation(
            ta_user, make_batch, make_candidate, make_invitation, link_valid_from=opens_at,
        )
        attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')
        token = issue_attempt_token(attempt)

        response = api_client.post(
            '/api/exam/begin/', HTTP_AUTHORIZATION=f'Bearer {token}',
        )

        assert response.status_code == 400
        assert response.data['opens_at'] == opens_at.isoformat()
        attempt.refresh_from_db()
        assert attempt.started_at is None


class TestExamTokenLandingReportsTheWindowOnExpiry:
    """The expired dead-end screen used to say only "this link has expired" with no way to know
    what the window even was. Reported live - the candidate had no way to tell whether they'd
    missed it by five minutes or five days. link_valid_from/link_valid_until now ride along so
    the frontend can show the actual dates.
    """

    def test_expired_response_carries_the_batchs_window(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation
    ):
        link_from = timezone.now() - timedelta(days=3)
        link_until = timezone.now() - timedelta(days=1)
        batch = make_batch(
            ta_user, link_valid_from=link_from, link_valid_until=link_until,
            logical_questions=0, quantitative_questions=0,
            verbal_questions=0, programming_questions=0,
        )
        candidate = make_candidate(batch, ta_user)
        invitation = make_invitation(candidate, ta_user, link_expired_at=link_until)

        response = api_client.get(f'/api/exam/token/{invitation.unique_link_token}/')

        assert response.status_code == 200
        assert response.data['reason'] == 'expired'
        assert response.data['link_valid_from'] == link_from.isoformat()
        assert response.data['link_valid_until'] == link_until.isoformat()
