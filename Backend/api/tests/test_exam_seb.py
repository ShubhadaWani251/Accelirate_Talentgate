"""Safe Exam Browser integration: config generation, request-hash verification, and the
monotonic "credit it once, never take it back" recording rule.

The one property every test here ultimately serves: SEB is a strong recommendation, never a
requirement enforced by this backend. A candidate who never sends a SEB header must sail through
the entire flow exactly as today - see TestARegularBrowserCandidateIsNeverBlocked, which is the
direct, automated proof of that and deliberately the first class in this file.
"""
import hashlib
import plistlib
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from api.models import ExamAttempt, Question, QuestionBankSection
from api.services import seb


@pytest.fixture
def invitation(ta_user, make_batch, make_candidate, make_invitation):
    candidate = make_candidate(make_batch(ta_user), ta_user)
    return make_invitation(candidate, ta_user)


@pytest.fixture
def attempt(invitation):
    return ExamAttempt.objects.create(
        candidate=invitation.candidate, invitation=invitation,
        status=ExamAttempt.Status.IN_PROGRESS,
    )


def _valid_request(rf, invitation, path='/api/exam/begin/'):
    """A request carrying a correctly-computed X-SafeExamBrowser-RequestHash for this
    invitation - built the same way SEB itself would, independent of the code under test.
    """
    request = rf.get(path)
    key = seb._browser_exam_key(invitation)
    request.META['HTTP_X_SAFEEXAMBROWSER_REQUESTHASH'] = hashlib.sha256(
        (request.build_absolute_uri() + key).encode('utf-8')
    ).hexdigest()
    return request


class TestBuildConfig:
    def test_round_trips_through_plistlib(self, invitation, settings):
        settings.SEB_BROWSER_EXAM_KEY_SECRET = 'test-secret'

        parsed = plistlib.loads(seb.build_config(invitation))

        assert parsed['startURL'] == (
            f"{settings.FRONTEND_ORIGIN}/t/{invitation.unique_link_token}/"
        )
        assert parsed['allowVideoCapture'] is True
        assert parsed['allowAudioCapture'] is True
        assert 'browserExamKey' in parsed

    def test_browser_exam_key_is_deterministic_for_one_invitation(self, invitation, settings):
        settings.SEB_BROWSER_EXAM_KEY_SECRET = 'test-secret'

        assert seb._browser_exam_key(invitation) == seb._browser_exam_key(invitation)

    def test_two_different_invitations_get_different_keys(
        self, ta_user, make_batch, make_candidate, make_invitation, settings
    ):
        settings.SEB_BROWSER_EXAM_KEY_SECRET = 'test-secret'
        batch = make_batch(ta_user)
        invitation_a = make_invitation(make_candidate(batch, ta_user), ta_user)
        invitation_b = make_invitation(make_candidate(batch, ta_user), ta_user)

        assert seb._browser_exam_key(invitation_a) != seb._browser_exam_key(invitation_b)

    def test_browser_exam_key_is_omitted_when_the_secret_is_unset(self, invitation, settings):
        settings.SEB_BROWSER_EXAM_KEY_SECRET = ''

        parsed = plistlib.loads(seb.build_config(invitation))

        assert 'browserExamKey' not in parsed
        # The rest of the config is unaffected - a candidate can still be offered SEB.
        assert parsed['allowVideoCapture'] is True


class TestVerifySebRequest:
    def test_a_correctly_computed_hash_verifies(self, invitation, rf, settings):
        settings.SEB_BROWSER_EXAM_KEY_SECRET = 'test-secret'

        assert seb.verify_seb_request(_valid_request(rf, invitation), invitation) is True

    def test_a_missing_header_does_not_verify(self, invitation, rf, settings):
        settings.SEB_BROWSER_EXAM_KEY_SECRET = 'test-secret'

        assert seb.verify_seb_request(rf.get('/api/exam/begin/'), invitation) is False

    def test_a_wrong_hash_does_not_verify(self, invitation, rf, settings):
        settings.SEB_BROWSER_EXAM_KEY_SECRET = 'test-secret'
        request = rf.get('/api/exam/begin/')
        request.META['HTTP_X_SAFEEXAMBROWSER_REQUESTHASH'] = 'not-a-real-hash'

        assert seb.verify_seb_request(request, invitation) is False

    def test_a_hash_computed_for_a_different_invitation_does_not_verify(
        self, ta_user, make_batch, make_candidate, make_invitation, rf, settings
    ):
        """The test that actually proves per-invitation scoping matters - not just that some
        plausible-looking hash is required, but that a hash genuinely valid for one candidate's
        link cannot be replayed against a different candidate's.
        """
        settings.SEB_BROWSER_EXAM_KEY_SECRET = 'test-secret'
        batch = make_batch(ta_user)
        invitation_a = make_invitation(make_candidate(batch, ta_user), ta_user)
        invitation_b = make_invitation(make_candidate(batch, ta_user), ta_user)

        request = _valid_request(rf, invitation_b)

        assert seb.verify_seb_request(request, invitation_a) is False

    def test_a_blank_secret_never_verifies_and_never_raises(self, invitation, rf, settings):
        settings.SEB_BROWSER_EXAM_KEY_SECRET = ''
        request = rf.get('/api/exam/begin/')
        request.META['HTTP_X_SAFEEXAMBROWSER_REQUESTHASH'] = 'anything-at-all'

        assert seb.verify_seb_request(request, invitation) is False


class TestRecordSebUsageIsMonotonic:
    def test_a_valid_header_sets_it(self, attempt, rf, settings):
        settings.SEB_BROWSER_EXAM_KEY_SECRET = 'test-secret'

        seb.record_seb_usage(attempt, _valid_request(rf, attempt.invitation), attempt.invitation)

        attempt.refresh_from_db()
        assert attempt.seb_verified_at is not None

    def test_a_later_request_with_no_header_does_not_clear_it(self, attempt, rf, settings):
        settings.SEB_BROWSER_EXAM_KEY_SECRET = 'test-secret'
        seb.record_seb_usage(attempt, _valid_request(rf, attempt.invitation), attempt.invitation)
        attempt.refresh_from_db()
        first_seen = attempt.seb_verified_at
        assert first_seen is not None

        seb.record_seb_usage(attempt, rf.get('/api/exam/begin/'), attempt.invitation)

        attempt.refresh_from_db()
        assert attempt.seb_verified_at == first_seen

    def test_the_earlier_of_two_valid_calls_wins_and_is_not_overwritten(self, attempt, rf, settings):
        """Simulates ExamIdentityCaptureView and ExamBeginView both eventually seeing a valid
        header - whichever runs first sets the timestamp, and the second is a no-op, not a
        second write.
        """
        settings.SEB_BROWSER_EXAM_KEY_SECRET = 'test-secret'
        seb.record_seb_usage(attempt, _valid_request(rf, attempt.invitation), attempt.invitation)
        attempt.refresh_from_db()
        first_seen = attempt.seb_verified_at

        seb.record_seb_usage(attempt, _valid_request(rf, attempt.invitation), attempt.invitation)

        attempt.refresh_from_db()
        assert attempt.seb_verified_at == first_seen

    def test_no_header_on_any_call_leaves_it_null(self, attempt, rf):
        seb.record_seb_usage(attempt, rf.get('/api/exam/begin/'), attempt.invitation)

        attempt.refresh_from_db()
        assert attempt.seb_verified_at is None


class TestARegularBrowserCandidateIsNeverBlocked:
    """The single most important property this integration has to hold: nothing about SEB may
    ever reject or degrade a candidate who simply never sends a SEB header. record_seb_usage in
    particular must never raise or alter attempt state in a way that could interfere with the
    exam continuing normally.
    """

    def test_record_seb_usage_is_a_silent_no_op_for_an_ordinary_request(self, attempt, rf):
        plain_request = rf.get('/api/exam/answers/1/')

        seb.record_seb_usage(attempt, plain_request, attempt.invitation)

        attempt.refresh_from_db()
        assert attempt.seb_verified_at is None
        assert attempt.status == ExamAttempt.Status.IN_PROGRESS


class TestExamSebConfigView:
    """HTTP-level: GET /api/exam/token/<token>/seb-config/, mirroring the request/rate-limit
    shape already proven correct for the sibling token-scoped views in test_exam_ratelimit_key.py.
    """

    def test_a_valid_invitation_gets_a_well_formed_seb_file(self, api_client, invitation, settings):
        settings.SEB_BROWSER_EXAM_KEY_SECRET = 'test-secret'

        response = api_client.get(f'/api/exam/token/{invitation.unique_link_token}/seb-config/')

        assert response.status_code == 200
        assert response['Content-Type'] == 'application/octet-stream'
        assert response['Content-Disposition'] == 'attachment; filename="talentgate-assessment.seb"'
        parsed = plistlib.loads(response.content)
        assert parsed['startURL'] == (
            f"{settings.FRONTEND_ORIGIN}/t/{invitation.unique_link_token}/"
        )

    def test_an_unknown_token_is_a_400_not_a_404_or_500(self, api_client, db):
        response = api_client.get('/api/exam/token/no-such-token/seb-config/')

        assert response.status_code == 400

    def test_an_expired_invitation_is_a_400(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user)
        invitation = make_invitation(
            candidate, ta_user, link_expired_at=timezone.now() - timedelta(days=1),
        )

        response = api_client.get(f'/api/exam/token/{invitation.unique_link_token}/seb-config/')

        assert response.status_code == 400

    def test_the_config_works_even_with_no_secret_configured(self, api_client, invitation, settings):
        """The whole point of decision #3 - an unconfigured deployment still hands out a working,
        downloadable .seb file, just without a browserExamKey embedded.
        """
        settings.SEB_BROWSER_EXAM_KEY_SECRET = ''

        response = api_client.get(f'/api/exam/token/{invitation.unique_link_token}/seb-config/')

        assert response.status_code == 200
        assert 'browserExamKey' not in plistlib.loads(response.content)


class TestExamSebConfigViewRateLimitIsPerCandidateNotPerIp:
    """Same shared-office-IP scenario as TestTokenLandingRateLimitIsPerCandidateNotPerIp in
    test_exam_ratelimit_key.py, for this endpoint's own 10/min limit.
    """
    SHARED_OFFICE_IP = {'REMOTE_ADDR': '203.0.113.9'}

    def _download(self, api_client, token):
        return api_client.get(
            f'/api/exam/token/{token}/seb-config/', **self.SHARED_OFFICE_IP,
        )

    def test_one_candidates_traffic_cannot_exhaust_a_different_candidates_budget(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation
    ):
        invitation_a = make_invitation(make_candidate(make_batch(ta_user), ta_user), ta_user)
        invitation_b = make_invitation(make_candidate(make_batch(ta_user), ta_user), ta_user)

        for _ in range(10):
            assert self._download(api_client, invitation_a.unique_link_token).status_code == 200
        assert self._download(api_client, invitation_a.unique_link_token).status_code == 429
        assert self._download(api_client, invitation_b.unique_link_token).status_code == 200


class TestFullFlowNeverBlocksAFallbackCandidate:
    """The single most important test in this file: a candidate who never sends the SEB header
    on any request, across the entire real flow - landing, verify-email, identity capture,
    begin, answer, submit - gets a normal 2xx throughout, and seb_verified_at stays null the
    whole way. This is the automated proof that "mandatory nudge, never a hard gate" actually
    holds end to end, not just at the unit level tested above.
    """

    @pytest.fixture
    def small_invitation(self, ta_user, make_batch, make_candidate, make_invitation):
        section = QuestionBankSection.objects.create(
            section_name='Logical & Analytical Reasoning', section_key='logical',
        )
        Question.objects.create(
            question_code='Q-SEB-FLOW-1', section=section, question_text='2 + 2 = ?',
            option_a='3', option_b='4', option_c='5', option_d='6', correct_option='B',
            difficulty=Question.Difficulty.EASY,
        )
        batch = make_batch(ta_user, logical_questions=1, quantitative_questions=0,
                           verbal_questions=0, programming_questions=0)
        candidate = make_candidate(batch, ta_user)
        return make_invitation(candidate, ta_user)

    def _identity_files(self):
        body = b'\xff\xd8\xff\xe0fake-jpeg-bytes'
        return {
            'id_photo': SimpleUploadedFile('id.jpg', body, content_type='image/jpeg'),
            'face_photo': SimpleUploadedFile('face.jpg', body, content_type='image/jpeg'),
        }

    def test_a_plain_browser_candidate_completes_the_entire_flow_with_2xx_throughout(
        self, api_client, small_invitation, settings
    ):
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True  # forces blob_storage's local-disk fallback, never reaches real Azure
        token = small_invitation.unique_link_token

        landing = api_client.get(f'/api/exam/token/{token}/')
        assert landing.status_code == 200
        assert landing.data == {'reason': 'ok', 'resume': False}

        verify = api_client.post(
            f'/api/exam/token/{token}/verify-email/',
            {'email': small_invitation.candidate.email},
        )
        assert verify.status_code == 200
        assert verify.data['resume'] is False

        identity = api_client.post(
            f'/api/exam/token/{token}/identity/', self._identity_files(), format='multipart',
        )
        assert identity.status_code == 200
        attempt_token = identity.data['attempt_token']

        api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {attempt_token}')

        begin = api_client.post('/api/exam/begin/')
        assert begin.status_code == 200
        question_id = begin.data['sections'][0]['questions'][0]['question_id']

        answer = api_client.patch(f'/api/exam/answers/{question_id}/', {'selected_option': 'B'})
        assert answer.status_code == 200

        submit = api_client.post('/api/exam/submit/')
        assert submit.status_code == 200

        attempt = ExamAttempt.objects.get(invitation=small_invitation)
        assert attempt.status == ExamAttempt.Status.SUBMITTED
        assert attempt.seb_verified_at is None
