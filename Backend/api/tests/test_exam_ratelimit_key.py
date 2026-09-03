"""Candidate exam-portal rate limiting has to be keyed on something that identifies ONE
candidate, not the network address they arrive from - see api/utils/net.py's
ratelimit_token_key/ratelimit_attempt_key.

Reported live: an internal load test of 10-15 people testing together failed the moment
everyone started their exam, even though nothing here should tax a single small server that
hard. The real cause: every candidate-facing endpoint keyed its rate limit on ratelimit_ip_key,
and get_client_ip() falls back to REMOTE_ADDR whenever TRUST_X_FORWARDED_FOR is off - the
documented, still-outstanding state of the real Azure App Service (see README's "Before go-live"
checklist). Behind Azure's own front-end proxy, REMOTE_ADDR is the SAME address for every
request from every user, not just people sharing one office - so a handful of candidates
loading their exam link within the same minute was enough to blow through a '5-10 requests/min'
ceiling sized for one abusive client, not a legitimate cohort. The fix scopes each limit to
whatever actually identifies a candidate - their invitation token before an attempt exists, the
attempt itself once one does - so one candidate's own traffic can never spend down another
candidate's budget, regardless of how IP addresses shake out in production.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from api.services import exam_session
from api.services.tokens import issue_attempt_token
from api.utils.net import ratelimit_attempt_key, ratelimit_token_key

pytestmark = pytest.mark.django_db


def _invitation(ta_user, make_batch, make_candidate, make_invitation):
    batch = make_batch(ta_user, logical_questions=0, quantitative_questions=0,
                       verbal_questions=0, programming_questions=0)
    candidate = make_candidate(batch, ta_user)
    return make_invitation(candidate, ta_user, link_expired_at=timezone.now() + timedelta(days=2))


class TestRatelimitTokenKey:
    """Unit-level: the key function itself, independent of django_ratelimit's machinery."""

    def test_keys_on_the_url_token_not_the_request_ip(self, rf):
        request = rf.get('/api/exam/token/abc-123/')
        request.META['REMOTE_ADDR'] = '10.0.0.1'
        request.resolver_match = SimpleNamespace(kwargs={'token': 'abc-123'})
        assert ratelimit_token_key('group', request) == 'abc-123'

    def test_two_different_tokens_from_the_same_ip_produce_different_keys(self, rf):
        request_a = rf.get('/x/')
        request_a.META['REMOTE_ADDR'] = '10.0.0.1'
        request_a.resolver_match = SimpleNamespace(kwargs={'token': 'token-a'})

        request_b = rf.get('/x/')
        request_b.META['REMOTE_ADDR'] = '10.0.0.1'
        request_b.resolver_match = SimpleNamespace(kwargs={'token': 'token-b'})

        assert ratelimit_token_key('group', request_a) != ratelimit_token_key('group', request_b)

    def test_falls_back_to_the_ip_when_no_token_is_resolved(self, rf):
        request = rf.get('/api/health/')
        request.META['REMOTE_ADDR'] = '10.0.0.7'
        request.resolver_match = SimpleNamespace(kwargs={})
        assert ratelimit_token_key('group', request) == '10.0.0.7'


class TestRatelimitAttemptKey:
    def test_keys_on_the_authenticated_attempt_not_the_request_ip(self, rf):
        request = rf.post('/api/exam/recording/chunk/')
        request.META['REMOTE_ADDR'] = '10.0.0.1'
        request.user = SimpleNamespace(attempt_id='attempt-xyz')
        assert ratelimit_attempt_key('group', request) == 'attempt-xyz'


class TestTokenLandingRateLimitIsPerCandidateNotPerIp:
    """HTTP-level: confirms the fix is actually wired through ExamTokenLandingView (10/min), not
    just correct in isolation, and reproduces the reported shape - many candidates, one IP.
    """
    SHARED_OFFICE_IP = {'REMOTE_ADDR': '203.0.113.9'}

    def _land(self, api_client, token):
        return api_client.get(f'/api/exam/token/{token}/', **self.SHARED_OFFICE_IP)

    def test_one_candidates_traffic_cannot_exhaust_a_different_candidates_budget(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation
    ):
        invitation_a = _invitation(ta_user, make_batch, make_candidate, make_invitation)
        invitation_b = _invitation(ta_user, make_batch, make_candidate, make_invitation)

        # Spend candidate A's own 10/min budget completely, all from the shared office IP.
        for _ in range(10):
            assert self._land(api_client, invitation_a.unique_link_token).status_code == 200
        # A's own 11th request in the same window is still correctly throttled...
        assert self._land(api_client, invitation_a.unique_link_token).status_code == 429
        # ...but candidate B, same IP, an entirely different link, has a full budget of their own.
        assert self._land(api_client, invitation_b.unique_link_token).status_code == 200


class TestRecordingChunkRateLimitIsPerAttemptNotPerIp:
    """HTTP-level counterpart for the authenticated side of the exam flow (30/min) - the
    continuous ~10s proctoring-video upload every candidate's browser makes for the whole exam.
    """
    SHARED_OFFICE_IP = {'REMOTE_ADDR': '203.0.113.9'}

    def _attempt_token(self, ta_user, make_batch, make_candidate, make_invitation):
        invitation = _invitation(ta_user, make_batch, make_candidate, make_invitation)
        attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')
        exam_session.begin_exam(attempt)
        return issue_attempt_token(attempt)

    def _upload(self, api_client, token):
        return api_client.post(
            '/api/exam/recording/chunk/', data=b'chunk-bytes',
            content_type='application/octet-stream',
            HTTP_AUTHORIZATION=f'Bearer {token}', **self.SHARED_OFFICE_IP,
        )

    def test_one_attempts_uploads_cannot_exhaust_a_different_attempts_budget(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation, settings
    ):
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True  # forces blob_storage's local-disk fallback, never reaches real Azure
        token_a = self._attempt_token(ta_user, make_batch, make_candidate, make_invitation)
        token_b = self._attempt_token(ta_user, make_batch, make_candidate, make_invitation)

        for _ in range(30):
            assert self._upload(api_client, token_a).status_code == 204
        assert self._upload(api_client, token_a).status_code == 429
        assert self._upload(api_client, token_b).status_code == 204
