"""Getting video off the request path, and telling a terminated candidate the truth.

Both of these come from the staging logs for 2026-10-05 13:14-14:10Z.

The deployment has four request slots in total (2 workers x 2 threads). Recording chunks were
POSTed through Django, which held a thread for the candidate's upload and then its own re-upload
to Azure: a median of 1.6s per chunk, a worst case of 36s, in-flight requests touching the
ceiling of 4, and ten requests failed by the platform without ever reaching Django. Video was
consuming the slots the exam needed, so it now goes straight to blob storage where it can.

And three candidates were shown "your assessment was ended and could not be reported to the
server, please contact the Staffing team" when their attempt had in fact been reported, recorded
and terminated for a named reason - the violation report simply lost the race with the request
that closed the attempt, and lost it to a 401 that carried no explanation.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from api.models import ExamAttempt
from api.services import blob_storage
from api.services import exam_session
from api.services.exam_session import TerminationReason
from api.services.tokens import issue_attempt_token


@pytest.fixture
def attempt(ta_user, make_batch, make_candidate, make_invitation, settings):
    settings.AZURE_STORAGE_CONNECTION_STRING = ''
    settings.DEBUG = True
    now = timezone.now()
    batch = make_batch(
        ta_user, logical_questions=0, quantitative_questions=0,
        verbal_questions=0, programming_questions=0,
        link_valid_from=now - timedelta(hours=1), link_valid_until=now + timedelta(hours=1),
    )
    candidate = make_candidate(batch, ta_user)
    invitation = make_invitation(candidate, ta_user)
    made, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')
    return made


class TestATerminatedCandidateIsToldWhy:
    """CandidateAttemptAuthentication rejects a closed attempt before any view runs, which makes
    record_violation's own 'already_closed' branch unreachable over HTTP. The 401 therefore has
    to carry the reason itself, or the candidate is told their exam failed to save.
    """

    def test_the_401_carries_the_real_termination_message(self, api_client, attempt):
        exam_session.record_violation(attempt, TerminationReason.SCREENSHOT_ATTEMPT)
        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.TERMINATED
        token = issue_attempt_token(attempt)

        # The violation report that lost the race - the shape that produced the false message.
        # SCREENSHOT_ATTEMPT is a first-occurrence termination (never warned), so one call ends it.
        response = api_client.post(
            '/api/exam/violation/', {'reason': 'tab_switch'},
            HTTP_AUTHORIZATION=f'Bearer {token}', format='json',
        )

        assert response.status_code == 401
        assert response.data['code'] == 'attempt_closed'
        assert response.data['reason'] == TerminationReason.SCREENSHOT_ATTEMPT
        # The candidate-facing text, not a generic "no longer active" - and specifically NOT the
        # "could not be reported to the server" the frontend falls back to.
        assert response.data['detail'] == (
            exam_session.TERMINATION_MESSAGES[TerminationReason.SCREENSHOT_ATTEMPT])

    def test_an_attempt_closed_without_a_reason_still_gets_a_usable_message(
        self, api_client, attempt,
    ):
        """A submitted attempt has no termination_reason, so the lookup must not hand back None
        and leave the candidate staring at an empty dialog."""
        exam_session.finalize_attempt(attempt, outcome='submitted')
        token = issue_attempt_token(attempt)

        response = api_client.post(
            '/api/exam/violation/', {'reason': 'tab_switch'},
            HTTP_AUTHORIZATION=f'Bearer {token}', format='json',
        )

        assert response.status_code == 401
        assert response.data['code'] == 'attempt_closed'
        assert response.data['detail']


class TestDirectRecordingUpload:
    def test_no_direct_url_is_offered_without_storage_configured(self, api_client, attempt):
        """The local-disk fallback cannot mint a SAS, and must say so rather than erroring: the
        client reads a null url as "keep using the server path", which still works.
        """
        token = issue_attempt_token(attempt)

        response = api_client.get(
            '/api/exam/recording/upload-url/', HTTP_AUTHORIZATION=f'Bearer {token}')

        assert response.status_code == 200
        assert response.data['url'] is None
        assert response.data['ttl_seconds'] == 0

    def test_the_server_upload_path_still_works(self, api_client, attempt):
        """Kept deliberately, and tested deliberately. Direct upload needs CORS on the storage
        account, which is an Azure-side change this code cannot make - so this path is what runs
        until that exists, and every direct failure falls back to it.
        """
        token = issue_attempt_token(attempt)

        response = api_client.post(
            '/api/exam/recording/chunk/', b'fake-webm-bytes',
            content_type='application/octet-stream', HTTP_AUTHORIZATION=f'Bearer {token}',
        )

        assert response.status_code == 204

    def test_a_closed_attempt_cannot_get_an_upload_url(self, api_client, attempt):
        """The URL is append-only and short-lived, but it is still a credential - it must die
        with the attempt rather than outlive it."""
        exam_session.record_violation(attempt, TerminationReason.SCREENSHOT_ATTEMPT)
        token = issue_attempt_token(attempt)

        response = api_client.get(
            '/api/exam/recording/upload-url/', HTTP_AUTHORIZATION=f'Bearer {token}')

        assert response.status_code == 401


class TestTheUploadDoesNotHoldADatabaseConnection:
    """A chunk upload must not keep a connection open while it receives the body.

    ReleaseDbConnectionMiddleware only closes connections once the response is finished, so the
    one authentication opens was held for the whole upload - a median of 1.6s and a worst case
    of 36s in the 2026-10-05 staging logs, inside a role limited to 15 connections on a shared
    server. The request stops needing the database within milliseconds of authenticating.

    This is the constraint that makes raising WEB_THREADS safe (api.checks' api.W005): the cap
    assumes every thread may hold a connection, and a thread parked on a slow candidate uplink
    is the one that least deserves to.

    ORDERING is what gets asserted, not a closed socket. pytest-django wraps each test in an
    outer atomic block, and Django's connection.close() deliberately will not drop a connection
    inside a transaction - it defers until the block exits. So the real close cannot be observed
    from a test at all, and asserting on it would only ever prove the harness. What this pins is
    the thing the production path actually depends on: the release happens BEFORE the body is
    read, not after the response like the middleware's.
    """

    def test_the_connection_is_released_before_the_body_is_read(
        self, api_client, attempt, monkeypatch,
    ):
        from django.db import connections as db_connections

        token = issue_attempt_token(attempt)
        order = []

        real_close = db_connections.close_all
        monkeypatch.setattr(db_connections, 'close_all',
                            lambda: (order.append('released'), real_close())[1])
        real_append = blob_storage.append_recording_chunk
        monkeypatch.setattr(blob_storage, 'append_recording_chunk',
                            lambda *a, **k: (order.append('chunk'), real_append(*a, **k))[1])

        response = api_client.post(
            '/api/exam/recording/chunk/', b'fake-webm-bytes',
            content_type='application/octet-stream', HTTP_AUTHORIZATION=f'Bearer {token}',
        )

        assert response.status_code == 204
        # 'released' before 'chunk' is the whole point. The middleware's own close_all runs
        # after the response, so it appears later in the list and never first.
        assert order[0] == 'released', (
            f'the database connection was not released before handling the chunk: {order}')
        assert 'chunk' in order
