"""Masked Aadhaar cards, and the VID that used to shadow the real number.

Both UIDAI's own e-Aadhaar download and DigiLocker now print a MASKED number by default -
"XXXX XXXX 5991", with no full number anywhere on the card. A candidate photographing that (or a
phone/laptop screen showing it) was rejected outright: services/aadhaar.py could only verify a
Verhoeff-checkable 12-digit run, and a masked card has none. Since a masked download is the
DEFAULT, this was not an edge case - it was most candidates without a physical card in hand.

Separate from test_aadhaar.py for the same reason test_aadhaar_pdf.py is: one card format, its
own fixtures, read on its own.

The three sample texts below are transcribed from real cards this was tested against - a UIDAI
e-Aadhaar photographed off a screen, a DigiLocker-issued Aadhaar, and a physical card. The
last-4 digits are rewritten to this file's fixture candidate so a match can be asserted; the
surrounding wording, the mask shape, the date formats and the VID are exactly as printed.
"""
from datetime import date

import pytest

from api.models import ExamAttempt
from api.services import aadhaar

pytestmark = pytest.mark.django_db

# Verhoeff-valid, and shared with test_aadhaar.py's own constant of the same name.
VALID_TEST_NUMBER = '234123412346'
TEST_DOB = date(1995, 8, 15)

# Masked, day-first date, photographed off a screen. Carries the card's own "Download Date" and
# "Issue Date" too - both date-shaped, which is exactly why _extract_dob prefers a labelled one.
EAADHAAR_MASKED_TEXT = (
    'Download Date:18/09/2026 Government of India Amey Chetan Dawkhar '
    'DOB: 15-08-1995 MALE Issue Date:20/09/2013 XXXX XXXX 2346'
)
# Masked, and a YEAR-FIRST date, which is DigiLocker's own format.
DIGILOCKER_MASKED_TEXT = (
    'GOVERNMENT OF INDIA AADHAAR Abcdef Ghijkl DOB: 1995/08/15 Female '
    'XXXX XXXX 2346 Address: House 70, Street Number 17 DigiLocker Verified'
)
# Unmasked, and prints a VID directly beneath the number - the collision this file also covers.
PHYSICAL_CARD_WITH_VID_TEXT = (
    'Government of India Amey Chetan Dawkhar DOB: 15-08-1995 MALE '
    '234123412346 VID : 9194 3855 4334 4604'
)


@pytest.fixture
def attempt(ta_user, make_batch, make_candidate, make_invitation):
    candidate = make_candidate(
        make_batch(ta_user), ta_user, aadhaar_last4='2346', date_of_birth=TEST_DOB,
    )
    invitation = make_invitation(candidate, ta_user)
    return ExamAttempt.objects.create(
        candidate=candidate, invitation=invitation, status=ExamAttempt.Status.IN_PROGRESS,
    )


class TestMaskedNumberExtraction:
    def test_a_uidai_e_aadhaar_masked_number_is_read(self):
        assert aadhaar._extract_masked_last4(EAADHAAR_MASKED_TEXT) == '2346'

    def test_a_digilocker_masked_number_is_read(self):
        assert aadhaar._extract_masked_last4(DIGILOCKER_MASKED_TEXT) == '2346'

    def test_an_unmasked_card_yields_no_masked_suffix(self):
        assert aadhaar._extract_masked_last4(PHYSICAL_CARD_WITH_VID_TEXT) is None

    def test_the_mask_survives_ocr_losing_the_spacing(self):
        # RapidOCR groups a line's glyphs by what it sees, so the two mask blocks can come back
        # run together or split, and a boxy uppercase X is routinely read as lowercase. None of
        # that is a reason to reject a genuine card.
        assert aadhaar._extract_masked_last4('AADHAAR XXXXXXXX 2346') == '2346'
        assert aadhaar._extract_masked_last4('AADHAAR xxxx xxxx 2346') == '2346'
        assert aadhaar._extract_masked_last4('AADHAAR **** **** 2346') == '2346'

    def test_two_different_masked_suffixes_are_ambiguous(self):
        # Two cards in one frame. Guessing which belongs to the candidate is not this function's
        # call - the same discipline the full-number path already applies.
        assert aadhaar._extract_masked_last4('XXXX XXXX 2346 XXXX XXXX 9999') is None

    def test_the_same_masked_suffix_printed_twice_is_not_ambiguous(self):
        # An e-Aadhaar prints its masked number more than once, exactly like an unmasked one.
        assert aadhaar._extract_masked_last4('XXXX XXXX 2346 ... XXXX XXXX 2346') == '2346'

    def test_a_mask_inside_a_word_is_not_a_match(self):
        assert aadhaar._extract_masked_last4('MAXXXXXXXX 2346') is None


class TestVidDoesNotShadowTheRealNumber:
    def test_a_card_printing_a_vid_still_yields_its_aadhaar_number(self):
        assert (aadhaar._extract_verhoeff_valid_number(PHYSICAL_CARD_WITH_VID_TEXT)
                == VALID_TEST_NUMBER)

    def test_a_verhoeff_passing_vid_no_longer_makes_the_card_ambiguous(self):
        # The real failure this prevents. A VID's first three groups are a 12-digit run ending
        # at a space, so _AADHAAR_RE offers it as a candidate like any other; it only has to
        # pass Verhoeff by chance - about one card in ten - to become a SECOND distinct valid
        # candidate, which _extract_verhoeff_valid_number reads as unresolvable ambiguity and
        # rejects the whole card for. This VID is built so its first 12 digits do pass, which is
        # what makes the assertion meaningful: without the strip it returns None.
        vid = VALID_TEST_NUMBER + '9999'
        assert aadhaar.verhoeff_is_valid(vid[:12])  # the shadowing candidate really is valid
        text = (
            f'Government of India DOB: 15-08-1995 {VALID_TEST_NUMBER} '
            f'VID : {vid[0:4]} {vid[4:8]} {vid[8:12]} {vid[12:16]}'
        )
        assert aadhaar._extract_verhoeff_valid_number(text) == VALID_TEST_NUMBER

    def test_a_vid_label_misread_by_ocr_is_still_stripped(self):
        assert aadhaar._VID_RE.search('V1D : 9194 3855 4334 4604') is not None
        assert aadhaar._VID_RE.search('vid 9194 3855 4334 4604') is not None

    def test_a_repeated_aadhaar_number_is_still_not_treated_as_a_vid(self):
        # The strip must not become an excuse to reject adjacent repeats - a real card prints
        # its own number more than once, which _extract_verhoeff_valid_number's dedupe handles.
        text = f'Government of India {VALID_TEST_NUMBER} {VALID_TEST_NUMBER}'
        assert aadhaar._extract_verhoeff_valid_number(text) == VALID_TEST_NUMBER


class TestDigiLockerDateFormat:
    def test_a_year_first_dob_is_parsed(self):
        assert aadhaar._extract_dob('DOB: 1995/08/15') == TEST_DOB

    def test_a_year_first_dob_wins_over_the_other_dates_on_the_card(self):
        assert aadhaar._extract_dob(DIGILOCKER_MASKED_TEXT) == TEST_DOB

    def test_the_day_first_format_is_unaffected(self):
        # The two patterns are structurally disjoint - a 4-2-2 date can never match 2-2-4 and
        # vice versa - so trying day-first first cannot shadow a year-first date, or the reverse.
        assert aadhaar._extract_dob('DOB: 15-08-1995') == TEST_DOB
        assert aadhaar._extract_dob(EAADHAAR_MASKED_TEXT) == TEST_DOB

    def test_an_impossible_year_first_date_is_not_accepted(self):
        assert aadhaar._extract_dob('DOB: 1995/13/45') is None


class TestVerdictFromOcrText:
    def test_a_masked_digilocker_card_with_the_right_dob_is_a_match(self, attempt, settings):
        # Pepper set explicitly: _hash_full_number returns None when it is blank, so without
        # this the "no hash" assertion below would pass for the wrong reason.
        settings.AADHAAR_HASH_PEPPER = 'test-pepper'
        assert aadhaar.verdict_from_ocr_text(attempt, DIGILOCKER_MASKED_TEXT) is True
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.MATCH
        assert (attempt.aadhaar_verification_method
                == ExamAttempt.AadhaarVerificationMethod.OCR_MASKED)
        assert attempt.aadhaar_decoded_last4 == '2346'
        # No full number exists on a masked card, so there is nothing to hash - and
        # find_hash_conflicts is therefore blind to these captures by construction. Asserted
        # rather than left implicit, because a TA reading a conflict list needs to know it only
        # covers unmasked captures.
        assert attempt.aadhaar_number_hash is None
        assert aadhaar.find_hash_conflicts(attempt) == []

    def test_a_masked_e_aadhaar_photographed_off_a_screen_is_a_match(self, attempt):
        assert aadhaar.verdict_from_ocr_text(attempt, EAADHAAR_MASKED_TEXT) is True
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.MATCH

    def test_a_masked_card_with_a_different_last4_is_a_mismatch(self, attempt):
        text = 'GOVERNMENT OF INDIA AADHAAR DOB: 15-08-1995 XXXX XXXX 9999'
        assert aadhaar.verdict_from_ocr_text(attempt, text) is True
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.MISMATCH

    def test_a_masked_card_with_the_wrong_dob_is_a_mismatch(self, attempt):
        # With no checksum available, the date is the only evidence besides the four digits -
        # so it has to be able to fail the card on its own.
        text = 'GOVERNMENT OF INDIA AADHAAR DOB: 19-11-2004 XXXX XXXX 2346'
        assert aadhaar.verdict_from_ocr_text(attempt, text) is True
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.MISMATCH

    def test_a_masked_card_with_no_readable_dob_stays_pending(self, attempt):
        # Never a MISMATCH: a date OCR could not read is not evidence against the candidate, and
        # they can simply retake the photo.
        text = 'GOVERNMENT OF INDIA AADHAAR XXXX XXXX 2346'
        assert aadhaar.verdict_from_ocr_text(attempt, text) is False
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.PENDING

    def test_a_masked_card_is_never_accepted_on_year_of_birth_alone(self, attempt):
        # parse_secure_qr's yob fallback exists for QRs carrying only a year. A masked card
        # always prints the full date, so accepting a year here would weaken the pairing for
        # nothing - _apply_masked_verdict passes no year deliberately.
        assert aadhaar._apply_masked_verdict(attempt, '2346', None) is False
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.PENDING

    def test_a_full_number_is_preferred_over_a_masked_one_in_the_same_text(self, attempt, settings):
        # An e-Aadhaar can show the masked number in the card art and the full one elsewhere.
        # The full number is strictly stronger evidence and is the only thing that produces the
        # cross-attempt hash, so it has to win - the hash is what proves which path ran.
        settings.AADHAAR_HASH_PEPPER = 'test-pepper'
        text = f'Government of India DOB: 15-08-1995 XXXX XXXX 2346 {VALID_TEST_NUMBER}'
        assert aadhaar.verdict_from_ocr_text(attempt, text) is True
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_method == ExamAttempt.AadhaarVerificationMethod.OCR
        assert attempt.aadhaar_number_hash is not None

    def test_a_masked_number_on_a_document_that_is_not_an_aadhaar_card_is_rejected(self, attempt):
        # The marker check is the ONLY document-type filter a masked card gets, since there is
        # no checksum to fall back on - so it has to run before the masked read, not after.
        text = 'MEMBERSHIP CARD DOB: 15-08-1995 XXXX XXXX 2346'
        assert aadhaar.verdict_from_ocr_text(attempt, text) is False
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.PENDING

    def test_an_unmasked_physical_card_with_a_vid_still_matches(self, attempt):
        assert aadhaar.verdict_from_ocr_text(attempt, PHYSICAL_CARD_WITH_VID_TEXT) is True
        attempt.refresh_from_db()
        assert attempt.aadhaar_verification_status == ExamAttempt.AadhaarVerificationStatus.MATCH
        assert attempt.aadhaar_verification_method == ExamAttempt.AadhaarVerificationMethod.OCR
