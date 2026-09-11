"""Aadhaar identity verification (services/aadhaar.py).

Only the last 4 digits and a one-way hash of a decoded Aadhaar number are ever stored anywhere -
the same data-minimisation stance test_candidate_identity.py already pins down for
Candidate.aadhaar_last4, extended here onto ExamAttempt. See services/aadhaar.py's own module
docstring for the two-path design (fast QR decode, deferred OCR fallback), the joint
last-4-plus-date-of-birth match requirement, and the hard-block-until-verified policy this
exercises.
"""

from datetime import date

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

# The DOB every test in this file that needs a matching candidate uses - the `attempt` fixture
# below sets the candidate's own date_of_birth to exactly this, so a test can build a QR/OCR
# payload that DOES or DOESN'T match it without depending on make_candidate's own
# counter-derived default.
TEST_DOB = date(1995, 8, 15)
TEST_DOB_QR_ATTR = '15-08-1995'  # DD-MM-YYYY, the shape parse_secure_qr's dob attribute expects
TEST_DOB_OCR_TEXT = 'DOB: 15-08-1995'  # what a candidate's card might actually print


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


def _legacy_qr_photo(uid, dob=None, yob=None):
    attrs = f'uid="{uid}" name="Test Person"'
    if dob:
        attrs += f' dob="{dob}"'
    if yob:
        attrs += f' yob="{yob}"'
    return _qr_image_bytes(f'<PrintLetterBarcodeData {attrs}/>')


def _printed_card_photo(lines):
    """A plain white image with each of `lines` rendered as real, OCR-able text - stands in for
    an Aadhaar card photo for the OCR-fallback tests below (no QR at all).
    """
    height = 60 * len(lines) + 20
    image = np.full((height, 480, 3), 255, dtype=np.uint8)
    for i, line in enumerate(lines):
        cv2.putText(image, line, (10, 50 + 60 * i), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
    ok, buf = cv2.imencode('.png', image)
    assert ok
    return buf.tobytes()


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
        assert result.dob is None
        assert result.dob_year is None

    def test_a_dob_attribute_is_parsed_into_a_full_date(self):
        result = aadhaar.parse_secure_qr(
            f'<PrintLetterBarcodeData uid="{VALID_TEST_NUMBER}" dob="{TEST_DOB_QR_ATTR}"/>'
        )
        assert result.dob == TEST_DOB
        assert result.dob_year is None

    def test_a_yob_attribute_is_parsed_when_dob_is_absent(self):
        result = aadhaar.parse_secure_qr(
            f'<PrintLetterBarcodeData uid="{VALID_TEST_NUMBER}" yob="1995"/>'
        )
        assert result.dob is None
        assert result.dob_year == 1995

    def test_an_unparseable_dob_attribute_falls_back_to_yob(self):
        result = aadhaar.parse_secure_qr(
            f'<PrintLetterBarcodeData uid="{VALID_TEST_NUMBER}" dob="not-a-date" yob="1995"/>'
        )
        assert result.dob is None
        assert result.dob_year == 1995

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


class TestLooksLikeAadhaarCard:
    def test_the_word_aadhaar_is_recognised(self):
        assert aadhaar._looks_like_aadhaar_card('Government of India Aadhaar 1234 5678 9012') is True

    def test_common_ocr_misspellings_are_still_recognised(self):
        assert aadhaar._looks_like_aadhaar_card('Aadhar Card 1234 5678 9012') is True

    def test_uidai_marker_is_recognised(self):
        assert aadhaar._looks_like_aadhaar_card('UIDAI 1234 5678 9012') is True

    def test_case_insensitive(self):
        assert aadhaar._looks_like_aadhaar_card('AADHAAR CARD') is True

    def test_unrelated_document_text_is_rejected(self):
        assert aadhaar._looks_like_aadhaar_card('Permanent Account Number Income Tax Department') is False


class TestExtractDob:
    def test_exactly_one_date_shaped_run_is_extracted(self):
        assert aadhaar._extract_dob('Name: Test DOB: 15-08-1995 Gender: M') == TEST_DOB

    def test_slash_and_dot_separators_are_also_accepted(self):
        assert aadhaar._extract_dob('DOB: 15/08/1995') == date(1995, 8, 15)
        assert aadhaar._extract_dob('DOB: 15.08.1995') == date(1995, 8, 15)

    def test_no_date_shaped_text_returns_none(self):
        assert aadhaar._extract_dob('no dates here at all') is None

    def test_a_labelled_dob_wins_over_an_ambiguous_second_date(self):
        """A real bug this pins down: EVERY genuine Aadhaar card also prints a separate
        "Aadhaar no. issued: DD/MM/YYYY" date in the identical DD/MM/YYYY shape - an earlier
        version of this function required exactly one date-shaped run in the whole text, which
        found two equally-plausible candidates on every single real card and returned None every
        time (confirmed against real production OCR text: '...issued:01/04/2012...
        DOB:13/10/2003...' - not a hypothetical, a real candidate stuck at PENDING for 8 attempts
        because of this). The "DOB" label - collapsed hard against the date, exactly as OCR
        renders it with no space - must now be preferred over the ambiguous whole-text scan.
        """
        assert aadhaar._extract_dob('DOB:15-08-1995 Issued:01-01-2020') == TEST_DOB
        assert aadhaar._extract_dob(
            'Government of India Aadhaarno.issued:01/04/2012 Test Person '
            'DOB:15/08/1995 Female 234123412346'
        ) == TEST_DOB

    def test_an_invalid_calendar_date_is_not_counted_as_a_candidate(self):
        # 35th month/day-shaped text isn't a real date, so this must still resolve unambiguously.
        assert aadhaar._extract_dob('Ref: 99-99-9999 DOB: 15-08-1995') == TEST_DOB

    def test_two_unlabelled_dates_with_no_dob_label_at_all_are_still_ambiguous(self):
        # No "DOB" label anywhere to disambiguate with - falls back to the old "exactly one, else
        # ambiguous" rule, same posture as _extract_verhoeff_valid_number.
        assert aadhaar._extract_dob('15-08-1995 and separately 01-01-2020') is None


@pytest.fixture
def attempt(ta_user, make_batch, make_candidate, make_invitation):
    candidate = make_candidate(
        make_batch(ta_user), ta_user, aadhaar_last4='2346', date_of_birth=TEST_DOB,
    )
    invitation = make_invitation(candidate, ta_user)
    return ExamAttempt.objects.create(
        candidate=candidate, invitation=invitation, status=ExamAttempt.Status.IN_PROGRESS,
    )


class TestVerifyIdentityPhoto:
    def test_disabled_by_default_leaves_the_attempt_pending(self, attempt, settings):
        settings.AADHAAR_VERIFICATION_ENABLED = False
        aadhaar.verify_identity_photo(attempt, _legacy_qr_photo(VALID_TEST_NUMBER, dob=TEST_DOB_QR_ATTR))
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.PENDING

    def test_a_matching_last_4_and_dob_is_recorded_as_a_match(self, attempt, settings):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        aadhaar.verify_identity_photo(attempt, _legacy_qr_photo(VALID_TEST_NUMBER, dob=TEST_DOB_QR_ATTR))
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.MATCH
        assert attempt.aadhaar_verification_method == ExamAttempt.AadhaarVerificationMethod.QR_LEGACY
        assert attempt.aadhaar_decoded_last4 == '2346'

    def test_a_matching_last_4_and_year_of_birth_is_recorded_as_a_match(self, attempt, settings):
        """Some legacy print-QR formats only carry a year (yob), not a full dob - still enough to
        confirm, per _apply_verdict's year-only comparison path.
        """
        settings.AADHAAR_VERIFICATION_ENABLED = True
        aadhaar.verify_identity_photo(attempt, _legacy_qr_photo(VALID_TEST_NUMBER, yob='1995'))
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.MATCH

    def test_a_different_last_4_is_recorded_as_a_mismatch(self, attempt, settings):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        attempt.candidate.aadhaar_last4 = '9999'
        attempt.candidate.save(update_fields=['aadhaar_last4'])
        aadhaar.verify_identity_photo(attempt, _legacy_qr_photo(VALID_TEST_NUMBER, dob=TEST_DOB_QR_ATTR))
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.MISMATCH

    def test_a_matching_last_4_but_different_dob_is_recorded_as_a_mismatch(self, attempt, settings):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        aadhaar.verify_identity_photo(attempt, _legacy_qr_photo(VALID_TEST_NUMBER, dob='01-01-1990'))
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.MISMATCH

    def test_no_dob_or_yob_on_the_qr_stays_pending_rather_than_matching_on_last4_alone(
        self, attempt, settings,
    ):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        aadhaar.verify_identity_photo(attempt, _legacy_qr_photo(VALID_TEST_NUMBER))
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.PENDING

    def test_candidate_with_no_dob_on_file_stays_pending_rather_than_mismatching(
        self, attempt, settings,
    ):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        attempt.candidate.date_of_birth = None
        attempt.candidate.save(update_fields=['date_of_birth'])
        aadhaar.verify_identity_photo(attempt, _legacy_qr_photo(VALID_TEST_NUMBER, dob=TEST_DOB_QR_ATTR))
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.PENDING

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
        aadhaar.verify_identity_photo(attempt, _legacy_qr_photo(INVALID_TEST_NUMBER, dob=TEST_DOB_QR_ATTR))
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
        aadhaar.verify_identity_photo(attempt, _legacy_qr_photo(VALID_TEST_NUMBER, dob=TEST_DOB_QR_ATTR))
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
        c1 = make_candidate(batch, ta_user, aadhaar_last4='2346', date_of_birth=TEST_DOB)
        c2 = make_candidate(batch, ta_user, aadhaar_last4='2346', date_of_birth=TEST_DOB)
        a1 = ExamAttempt.objects.create(
            candidate=c1, invitation=make_invitation(c1, ta_user),
            status=ExamAttempt.Status.IN_PROGRESS,
        )
        a2 = ExamAttempt.objects.create(
            candidate=c2, invitation=make_invitation(c2, ta_user),
            status=ExamAttempt.Status.IN_PROGRESS,
        )
        photo = _legacy_qr_photo(VALID_TEST_NUMBER, dob=TEST_DOB_QR_ATTR)
        aadhaar.verify_identity_photo(a1, photo)
        aadhaar.verify_identity_photo(a2, photo)

        conflicts = aadhaar.find_hash_conflicts(a1)
        assert len(conflicts) == 1
        assert conflicts[0]['candidate_id'] == c2.candidate_id

    def test_no_hash_yet_returns_no_conflicts(self, attempt):
        assert aadhaar.find_hash_conflicts(attempt) == []

    def test_a_candidates_own_other_attempt_never_conflicts_with_itself(self, attempt, settings):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        settings.AADHAAR_HASH_PEPPER = 'test-pepper'
        aadhaar.verify_identity_photo(attempt, _legacy_qr_photo(VALID_TEST_NUMBER, dob=TEST_DOB_QR_ATTR))
        assert aadhaar.find_hash_conflicts(attempt) == []


class TestIdentityCaptureNeverBlocksOnAadhaarBugs:
    """HTTP-level: a bug or crash inside services.aadhaar must never surface as an unhandled 500
    on the identity-capture endpoints - the verification OUTCOME can (and by policy now does)
    block progress, but a coding error in this module must not.
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
        candidate = make_candidate(
            batch, ta_user, aadhaar_last4='2346', date_of_birth=TEST_DOB,
        )
        return make_invitation(candidate, ta_user)

    def test_identity_capture_returns_200_with_a_real_matching_qr_photo(
        self, api_client, small_invitation, settings,
    ):
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        settings.AADHAAR_VERIFICATION_ENABLED = True
        token = small_invitation.unique_link_token

        api_client.post(
            f'/api/exam/token/{token}/verify-email/', {'email': small_invitation.candidate.email},
        )
        photo = _legacy_qr_photo(VALID_TEST_NUMBER, dob=TEST_DOB_QR_ATTR)
        aadhaar_response = api_client.post(
            f'/api/exam/token/{token}/identity/aadhaar/',
            {'id_photo': SimpleUploadedFile('id.png', photo, content_type='image/png')},
            format='multipart',
        )
        assert aadhaar_response.status_code == 200
        assert aadhaar_response.data['aadhaar_verification_status'] == 'match'

        response = api_client.post(
            f'/api/exam/token/{token}/identity/',
            {'face_photo': SimpleUploadedFile(
                'face.jpg', b'\xff\xd8\xff\xe0fake-jpeg-bytes', content_type='image/jpeg',
            )},
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
        aadhaar_response = api_client.post(
            f'/api/exam/token/{token}/identity/aadhaar/',
            {'id_photo': SimpleUploadedFile(
                'id.jpg', b'\xff\xd8\xff\xe0fake-jpeg-bytes', content_type='image/jpeg',
            )},
            format='multipart',
        )
        assert aadhaar_response.status_code == 200


class TestCanRetry:
    def test_can_retry_while_not_matched(self, attempt):
        assert aadhaar.can_retry(attempt) is True
        attempt.aadhaar_verification_status = ExamAttempt.AadhaarVerificationStatus.MISMATCH
        assert aadhaar.can_retry(attempt) is True

    def test_cannot_retry_once_matched(self, attempt):
        attempt.aadhaar_verification_status = ExamAttempt.AadhaarVerificationStatus.MATCH
        assert aadhaar.can_retry(attempt) is False

    def test_unlimited_regardless_of_how_many_attempts_have_been_used(self, attempt):
        """By policy there is no cap any more - see aadhaar.py's module docstring."""
        attempt.aadhaar_verification_attempts = 500
        assert aadhaar.can_retry(attempt) is True


class TestTryOcrInline:
    """The RapidOCR-backed synchronous fallback, only ever reached when the fast QR path leaves
    an attempt PENDING. Requires a Verhoeff-valid number, Aadhaar-specific wording, AND a
    matching date of birth - not the number alone - before recording a match.
    """

    def test_a_readable_matching_card_gets_a_verdict(self, attempt, settings):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        photo = _printed_card_photo(['Government of India', 'Aadhaar', VALID_TEST_NUMBER, TEST_DOB_OCR_TEXT])
        assert aadhaar.try_ocr_inline(attempt, photo) is True
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.MATCH
        assert attempt.aadhaar_verification_method == ExamAttempt.AadhaarVerificationMethod.OCR

    def test_a_valid_number_without_aadhaar_wording_is_rejected(self, attempt, settings):
        """Some other document that happens to carry a passing 12-digit number must not be
        accepted just because the digits check out - see _looks_like_aadhaar_card.
        """
        settings.AADHAAR_VERIFICATION_ENABLED = True
        photo = _printed_card_photo(['Income Tax Department', VALID_TEST_NUMBER, TEST_DOB_OCR_TEXT])
        assert aadhaar.try_ocr_inline(attempt, photo) is False
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.PENDING

    def test_a_valid_number_and_aadhaar_wording_but_no_dob_stays_pending(self, attempt, settings):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        photo = _printed_card_photo(['Aadhaar', VALID_TEST_NUMBER])
        assert aadhaar.try_ocr_inline(attempt, photo) is False
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.PENDING

    def test_garbage_bytes_return_false_not_raise(self, attempt, settings):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        assert aadhaar.try_ocr_inline(attempt, b'garbage, not an image') is False

    def test_skipped_outright_when_no_concurrency_slot_is_free(self, attempt, settings):
        settings.AADHAAR_VERIFICATION_ENABLED = True
        # A photo that DOES resolve when a slot is free (proven by the sibling test above) - held
        # unreadable here only because the semaphore is occupied, exactly like a concurrent
        # request would leave it. Confirms the guard actually skips work, not just coincidentally
        # returns False.
        photo = _printed_card_photo(['Government of India', 'Aadhaar', VALID_TEST_NUMBER, TEST_DOB_OCR_TEXT])
        assert aadhaar._ocr_semaphore.acquire(blocking=False) is True
        try:
            assert aadhaar.try_ocr_inline(attempt, photo) is False
            attempt.refresh_from_db()
            assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.PENDING
        finally:
            aadhaar._ocr_semaphore.release()


class TestAadhaarCaptureRetryFlow:
    """HTTP-level: the two-step capture flow (Aadhaar photo with unlimited retries, then face
    photo, which is now hard-gated on a confirmed match).
    """

    @pytest.fixture
    def small_invitation(self, ta_user, make_batch, make_candidate, make_invitation):
        section = QuestionBankSection.objects.create(
            section_name='Logical & Analytical Reasoning', section_key='logical',
        )
        Question.objects.create(
            question_code='Q-AADHAAR-RETRY-1', section=section, question_text='2 + 2 = ?',
            option_a='3', option_b='4', option_c='5', option_d='6', correct_option='B',
            difficulty=Question.Difficulty.EASY,
        )
        batch = make_batch(ta_user, logical_questions=1, quantitative_questions=0,
                           verbal_questions=0, programming_questions=0)
        candidate = make_candidate(
            batch, ta_user, aadhaar_last4='2346', date_of_birth=TEST_DOB,
        )
        return make_invitation(candidate, ta_user)

    def _capture(self, api_client, token, photo_bytes):
        return api_client.post(
            f'/api/exam/token/{token}/identity/aadhaar/',
            {'id_photo': SimpleUploadedFile('id.png', photo_bytes, content_type='image/png')},
            format='multipart',
        )

    def _face_photo(self, api_client, token):
        return api_client.post(
            f'/api/exam/token/{token}/identity/',
            {'face_photo': SimpleUploadedFile(
                'face.jpg', b'\xff\xd8\xff\xe0fake-jpeg-bytes', content_type='image/jpeg',
            )},
            format='multipart',
        )

    def test_a_match_on_first_try_needs_no_retry(self, api_client, small_invitation, settings):
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        settings.AADHAAR_VERIFICATION_ENABLED = True
        token = small_invitation.unique_link_token
        api_client.post(f'/api/exam/token/{token}/verify-email/',
                         {'email': small_invitation.candidate.email})

        photo = _legacy_qr_photo(VALID_TEST_NUMBER, dob=TEST_DOB_QR_ATTR)
        response = self._capture(api_client, token, photo)
        assert response.status_code == 200
        assert response.data['aadhaar_verification_status'] == 'match'
        assert response.data['aadhaar_can_retry'] is False
        assert response.data['aadhaar_attempts_used'] == 1

        face_response = self._face_photo(api_client, token)
        assert face_response.status_code == 200

    def test_unreadable_photos_can_be_retried_without_limit(
        self, api_client, small_invitation, settings,
    ):
        """By policy there is no cap and no "proceed anyway" - unlike the earlier design, a
        candidate stuck on an unreadable photo simply keeps retrying, and the face-photo step
        (and thus the exam) never becomes reachable until one finally matches.
        """
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        settings.AADHAAR_VERIFICATION_ENABLED = True
        token = small_invitation.unique_link_token
        api_client.post(f'/api/exam/token/{token}/verify-email/',
                         {'email': small_invitation.candidate.email})

        blank = np.full((200, 200), 255, dtype=np.uint8)
        ok, buf = cv2.imencode('.png', blank)
        assert ok
        unreadable_photo = buf.tobytes()

        # Four straight failures - well past the old 2-attempt cap, to prove there genuinely is
        # none any more. Five total calls to this endpoint in the test (four here, one more
        # below) stays at, not over, its own 5/m anti-abuse rate limit.
        for expected_attempts in range(1, 5):
            response = self._capture(api_client, token, unreadable_photo)
            assert response.status_code == 200
            assert response.data['aadhaar_verification_status'] == 'pending'
            assert response.data['aadhaar_can_retry'] is True
            assert response.data['aadhaar_attempts_used'] == expected_attempts

        # Still blocked from the exam after four failed tries - by design, no escape valve.
        face_response = self._face_photo(api_client, token)
        assert face_response.status_code == 400

        # A later correct capture still succeeds and unblocks it.
        good_photo = _legacy_qr_photo(VALID_TEST_NUMBER, dob=TEST_DOB_QR_ATTR)
        response = self._capture(api_client, token, good_photo)
        assert response.data['aadhaar_verification_status'] == 'match'
        face_response = self._face_photo(api_client, token)
        assert face_response.status_code == 200

    def test_retrying_after_an_ocr_mismatch_actually_reverifies(
        self, api_client, small_invitation, settings,
    ):
        """A real bug this test exists specifically to pin down: the OCR fallback was only tried
        when the attempt's stored status was still PENDING, so a candidate whose first attempt
        came back MISMATCH (rather than unreadable/PENDING) got the exact same stale MISMATCH
        verdict back on every retry, forever - try_ocr_inline was silently never called again,
        no matter how many times they retook the photo. This only affects the OCR path (a card
        with no decodable QR): the QR path (verify_identity_photo) calls _apply_verdict
        unconditionally on every submission regardless of the attempt's current status, so it
        never had this gap. Caught via manual end-to-end testing against a real running dev
        server, not by any test that existed before this one - every prior retry test only ever
        exercised PENDING -> PENDING -> ... -> MATCH, never MISMATCH -> retry.
        """
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        settings.AADHAAR_VERIFICATION_ENABLED = True
        token = small_invitation.unique_link_token
        api_client.post(f'/api/exam/token/{token}/verify-email/',
                         {'email': small_invitation.candidate.email})

        # Right number (last4 matches), wrong date of birth - a genuine MISMATCH verdict via OCR,
        # not PENDING. No QR in either photo, so only the OCR path is ever in play here.
        wrong_dob_photo = _printed_card_photo(['Aadhaar', VALID_TEST_NUMBER, 'DOB: 01-01-1990'])
        response = self._capture(api_client, token, wrong_dob_photo)
        assert response.status_code == 200
        assert response.data['aadhaar_verification_status'] == 'mismatch'
        assert response.data['aadhaar_can_retry'] is True

        # Retaking with the correct date of birth must re-run OCR and actually match - if the old
        # PENDING-only gate regresses, this comes back 'mismatch' again instead.
        correct_photo = _printed_card_photo(['Aadhaar', VALID_TEST_NUMBER, TEST_DOB_OCR_TEXT])
        response = self._capture(api_client, token, correct_photo)
        assert response.status_code == 200
        assert response.data['aadhaar_verification_status'] == 'match'
        assert response.data['aadhaar_can_retry'] is False

        face_response = self._face_photo(api_client, token)
        assert face_response.status_code == 200

    def test_face_photo_endpoint_requires_aadhaar_capture_first(
        self, api_client, small_invitation, settings,
    ):
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        token = small_invitation.unique_link_token
        api_client.post(f'/api/exam/token/{token}/verify-email/',
                         {'email': small_invitation.candidate.email})

        response = self._face_photo(api_client, token)
        assert response.status_code == 400

    def test_face_photo_endpoint_refuses_an_unmatched_aadhaar_when_the_feature_is_enabled(
        self, api_client, small_invitation, settings,
    ):
        """The real enforcement point for the hard-block policy - a candidate who somehow calls
        this endpoint directly, bypassing the frontend's own gating, is still refused.
        """
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        settings.AADHAAR_VERIFICATION_ENABLED = True
        token = small_invitation.unique_link_token
        api_client.post(f'/api/exam/token/{token}/verify-email/',
                         {'email': small_invitation.candidate.email})

        blank = np.full((200, 200), 255, dtype=np.uint8)
        ok, buf = cv2.imencode('.png', blank)
        assert ok
        self._capture(api_client, token, buf.tobytes())  # stays pending, never matched

        response = self._face_photo(api_client, token)
        assert response.status_code == 400
        assert 'detail' in response.data

    def test_unlimited_retries_while_the_feature_is_disabled(
        self, api_client, small_invitation, settings,
    ):
        """AADHAAR_VERIFICATION_ENABLED defaults to False in every real deployment today - this
        endpoint's retry behaviour must stay exactly as unlimited/non-blocking as it is with the
        feature on, and the face-photo step must not be gated at all.
        """
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        settings.AADHAAR_VERIFICATION_ENABLED = False
        token = small_invitation.unique_link_token
        api_client.post(f'/api/exam/token/{token}/verify-email/',
                         {'email': small_invitation.candidate.email})

        photo = SimpleUploadedFile(
            'id.jpg', b'\xff\xd8\xff\xe0fake-jpeg-bytes', content_type='image/jpeg',
        )
        for _ in range(5):
            response = api_client.post(
                f'/api/exam/token/{token}/identity/aadhaar/', {'id_photo': photo},
                format='multipart',
            )
            assert response.status_code == 200
            assert response.data['aadhaar_can_retry'] is True
            assert response.data['aadhaar_attempts_used'] == 0

        face_response = self._face_photo(api_client, token)
        assert face_response.status_code == 200
