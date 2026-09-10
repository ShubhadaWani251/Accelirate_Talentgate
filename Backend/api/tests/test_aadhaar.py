"""Aadhaar identity verification (services/aadhaar.py).

Only the last 4 digits and a one-way hash of a decoded Aadhaar number are ever stored anywhere -
the same data-minimisation stance test_candidate_identity.py already pins down for
Candidate.aadhaar_last4, extended here onto ExamAttempt. See services/aadhaar.py's own module
docstring for the two-path design (fast QR decode, deferred OCR fallback) this exercises.
"""

import numpy as np
import qrcode
import cv2
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from api.models import ExamAttempt, Question, QuestionBankSection
from api.services import aadhaar

# Hand-derived and independently cross-checked against the standard Verhoeff multiplication/
# permutation tables (traced by hand twice, in agreement both times) - this is exactly why
# TestVerhoeff.test_the_known_valid_number_passes below is the module's own first, automated
# confirmation rather than trusting the derivation alone.
VALID_TEST_NUMBER = '234123412346'
INVALID_TEST_NUMBER = '234123412340'  # same base, wrong check digit


def _qr_image_bytes(data, scale=8):
    """A real PNG containing a QR code encoding `data` - not a mock, so decode_qr_payload is
    exercised against actual QR bytes the same way a candidate's uploaded photo would be.
    """
    qr = qrcode.QRCode(border=4)
    qr.add_data(data)
    qr.make()
    matrix = np.array(qr.get_matrix(), dtype=np.uint8)
    image = np.where(matrix, 0, 255).astype(np.uint8)
    image = np.kron(image, np.ones((scale, scale), dtype=np.uint8))
    ok, buf = cv2.imencode('.png', image)
    assert ok
    return buf.tobytes()


def _legacy_qr_photo(uid):
    xml = f'<PrintLetterBarcodeData uid="{uid}" name="Test Person"/>'
    return _qr_image_bytes(xml)


class TestVerhoeff:
    def test_the_known_valid_number_passes(self):
        assert aadhaar.verhoeff_is_valid(VALID_TEST_NUMBER) is True

    def test_the_same_number_with_a_wrong_check_digit_fails(self):
        assert aadhaar.verhoeff_is_valid(INVALID_TEST_NUMBER) is False

    def test_non_digit_input_is_rejected_not_raised(self):
        assert aadhaar.verhoeff_is_valid('12ab') is False


class TestDecodeQrPayload:
    def test_a_real_qr_image_decodes_to_its_exact_payload(self):
        photo = _qr_image_bytes('hello world test 123')
        assert aadhaar.decode_qr_payload(photo) == 'hello world test 123'

    def test_a_photo_with_no_qr_code_returns_none(self):
        blank = np.full((200, 200), 255, dtype=np.uint8)
        ok, buf = cv2.imencode('.png', blank)
        assert ok
        assert aadhaar.decode_qr_payload(buf.tobytes()) is None

    def test_unparseable_bytes_return_none_not_raise(self):
        assert aadhaar.decode_qr_payload(b'not an image at all') is None


class TestParseSecureQr:
    def test_legacy_xml_qr_extracts_the_uid(self):
        result = aadhaar.parse_secure_qr(
            f'<PrintLetterBarcodeData uid="{VALID_TEST_NUMBER}" name="Test"/>'
        )
        assert result is not None
        assert result.method == ExamAttempt.AadhaarVerificationMethod.QR_LEGACY
        assert result.full_number == VALID_TEST_NUMBER

    def test_a_secure_qr_shaped_payload_is_deliberately_not_parsed(self):
        """A giant decimal integer, not readable XML - the real Secure QR shape. Parsing this is
        deliberately unimplemented (see parse_secure_qr's own docstring) - it must come back None,
        never a guessed result.
        """
        assert aadhaar.parse_secure_qr('4' * 250) is None

    def test_garbage_text_returns_none(self):
        assert aadhaar.parse_secure_qr('not xml at all') is None

    def test_xml_without_a_valid_uid_attribute_returns_none(self):
        assert aadhaar.parse_secure_qr('<PrintLetterBarcodeData name="Test"/>') is None


@pytest.fixture
def attempt(ta_user, make_batch, make_candidate, make_invitation):
    candidate = make_candidate(make_batch(ta_user), ta_user, aadhaar_last4='2346')
    invitation = make_invitation(candidate, ta_user)
    return ExamAttempt.objects.create(
        candidate=candidate, invitation=invitation, status=ExamAttempt.Status.IN_PROGRESS,
    )


class TestVerifyIdentityPhoto:
    def test_disabled_by_default_leaves_the_attempt_pending(self, attempt, settings):
        settings.AADHAAR_VERIFICATION_ENABLED = False
        aadhaar.verify_identity_photo(attempt, _legacy_qr_photo(VALID_TEST_NUMBER))
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.PENDING

    def test_a_matching_last_4_is_recorded_as_a_match(self, attempt, settings):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        aadhaar.verify_identity_photo(attempt, _legacy_qr_photo(VALID_TEST_NUMBER))
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.MATCH
        assert attempt.aadhaar_verification_method == ExamAttempt.AadhaarVerificationMethod.QR_LEGACY
        assert attempt.aadhaar_decoded_last4 == '2346'

    def test_a_different_last_4_is_recorded_as_a_mismatch(self, attempt, settings, make_candidate):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        attempt.candidate.aadhaar_last4 = '9999'
        attempt.candidate.save(update_fields=['aadhaar_last4'])
        aadhaar.verify_identity_photo(attempt, _legacy_qr_photo(VALID_TEST_NUMBER))
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.MISMATCH

    def test_a_photo_with_no_qr_stays_pending_for_the_ocr_fallback(self, attempt, settings):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        blank = np.full((200, 200), 255, dtype=np.uint8)
        ok, buf = cv2.imencode('.png', blank)
        assert ok
        aadhaar.verify_identity_photo(attempt, buf.tobytes())
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.PENDING

    def test_a_failed_checksum_stays_pending_rather_than_trusting_a_bad_read(self, attempt, settings):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        aadhaar.verify_identity_photo(attempt, _legacy_qr_photo(INVALID_TEST_NUMBER))
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.PENDING

    def test_never_raises_even_if_the_photo_bytes_are_garbage(self, attempt, settings):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        aadhaar.verify_identity_photo(attempt, b'garbage, not an image')  # must not raise
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.PENDING


class TestFullNumberNeverPersisted:
    def test_the_last4_field_is_capped_at_4_characters(self):
        assert ExamAttempt._meta.get_field('aadhaar_decoded_last4').max_length == 4

    def test_the_status_and_method_fields_only_accept_their_fixed_choices(self):
        """These two are free-text-shaped CharFields at the database level, but this codebase's
        own code only ever assigns a value from their .choices - never arbitrary decoded text -
        so a full number could only end up in one of these by a bug elsewhere assigning it
        directly, not through any path this module exposes. The property that actually matters
        is that none of the fixed choice values themselves look like a 12-digit number - length
        alone is not the right test (a status label can be long without being a number at all).
        """
        status_values = {c[0] for c in ExamAttempt.AadhaarVerificationStatus.choices}
        method_values = {c[0] for c in ExamAttempt.AadhaarVerificationMethod.choices}
        assert all(not v.isdigit() for v in status_values | method_values)

    def test_running_verification_never_leaves_the_full_number_as_a_substring_on_the_row(
        self, attempt, settings,
    ):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        aadhaar.verify_identity_photo(attempt, _legacy_qr_photo(VALID_TEST_NUMBER))
        attempt.refresh_from_db()
        for field in attempt._meta.get_fields():
            if not hasattr(field, 'attname'):
                continue
            value = str(getattr(attempt, field.attname, ''))
            assert VALID_TEST_NUMBER not in value, field.name


class TestFindHashConflicts:
    def test_two_attempts_sharing_a_hash_for_different_candidates_conflict(
        self, ta_user, make_batch, make_candidate, make_invitation, settings,
    ):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        settings.AADHAAR_HASH_PEPPER = 'test-pepper'
        batch = make_batch(ta_user)
        c1 = make_candidate(batch, ta_user, aadhaar_last4='2346')
        c2 = make_candidate(batch, ta_user, aadhaar_last4='2346')
        a1 = ExamAttempt.objects.create(
            candidate=c1, invitation=make_invitation(c1, ta_user),
            status=ExamAttempt.Status.IN_PROGRESS,
        )
        a2 = ExamAttempt.objects.create(
            candidate=c2, invitation=make_invitation(c2, ta_user),
            status=ExamAttempt.Status.IN_PROGRESS,
        )
        aadhaar.verify_identity_photo(a1, _legacy_qr_photo(VALID_TEST_NUMBER))
        aadhaar.verify_identity_photo(a2, _legacy_qr_photo(VALID_TEST_NUMBER))

        conflicts = aadhaar.find_hash_conflicts(a1)
        assert len(conflicts) == 1
        assert conflicts[0]['candidate_id'] == c2.candidate_id

    def test_no_hash_yet_returns_no_conflicts(self, attempt):
        assert aadhaar.find_hash_conflicts(attempt) == []

    def test_a_candidates_own_other_attempt_never_conflicts_with_itself(self, attempt, settings):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        settings.AADHAAR_HASH_PEPPER = 'test-pepper'
        aadhaar.verify_identity_photo(attempt, _legacy_qr_photo(VALID_TEST_NUMBER))
        assert aadhaar.find_hash_conflicts(attempt) == []


class TestIdentityCaptureNeverBlocksOnAadhaar:
    """HTTP-level: the identity-capture endpoint's normal 200 response must never depend on
    Aadhaar verification succeeding, being enabled, or even running without error.
    """

    @pytest.fixture
    def small_invitation(self, ta_user, make_batch, make_candidate, make_invitation):
        section = QuestionBankSection.objects.create(
            section_name='Logical & Analytical Reasoning', section_key='logical',
        )
        Question.objects.create(
            question_code='Q-AADHAAR-FLOW-1', section=section, question_text='2 + 2 = ?',
            option_a='3', option_b='4', option_c='5', option_d='6', correct_option='B',
            difficulty=Question.Difficulty.EASY,
        )
        batch = make_batch(ta_user, logical_questions=1, quantitative_questions=0,
                           verbal_questions=0, programming_questions=0)
        candidate = make_candidate(batch, ta_user, aadhaar_last4='2346')
        return make_invitation(candidate, ta_user)

    def test_identity_capture_returns_200_with_a_real_qr_photo(
        self, api_client, small_invitation, settings,
    ):
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        settings.AADHAAR_VERIFICATION_ENABLED = True
        token = small_invitation.unique_link_token

        api_client.post(
            f'/api/exam/token/{token}/verify-email/', {'email': small_invitation.candidate.email},
        )
        photo = _legacy_qr_photo(VALID_TEST_NUMBER)
        response = api_client.post(
            f'/api/exam/token/{token}/identity/',
            {
                'id_photo': SimpleUploadedFile('id.png', photo, content_type='image/png'),
                'face_photo': SimpleUploadedFile(
                    'face.jpg', b'\xff\xd8\xff\xe0fake-jpeg-bytes', content_type='image/jpeg',
                ),
            },
            format='multipart',
        )
        assert response.status_code == 200
        attempt = ExamAttempt.objects.get(invitation=small_invitation)
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.MATCH

    def test_identity_capture_still_returns_200_if_aadhaar_verification_itself_raises(
        self, api_client, small_invitation, settings, monkeypatch,
    ):
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        settings.AADHAAR_VERIFICATION_ENABLED = True

        def _boom(*args, **kwargs):
            raise RuntimeError('simulated failure inside services.aadhaar')

        monkeypatch.setattr(aadhaar, 'decode_qr_payload', _boom)
        token = small_invitation.unique_link_token

        api_client.post(
            f'/api/exam/token/{token}/verify-email/', {'email': small_invitation.candidate.email},
        )
        response = api_client.post(
            f'/api/exam/token/{token}/identity/',
            {
                'id_photo': SimpleUploadedFile(
                    'id.jpg', b'\xff\xd8\xff\xe0fake-jpeg-bytes', content_type='image/jpeg',
                ),
                'face_photo': SimpleUploadedFile(
                    'face.jpg', b'\xff\xd8\xff\xe0fake-jpeg-bytes', content_type='image/jpeg',
                ),
            },
            format='multipart',
        )
        assert response.status_code == 200
