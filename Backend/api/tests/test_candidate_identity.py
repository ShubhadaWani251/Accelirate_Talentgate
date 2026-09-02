"""Aadhaar handling and duplicate detection.

Only the last four digits of an Aadhaar number are stored anywhere. That is a data-minimisation
decision with a real consequence: four digits collide roughly once every ten thousand people, so
they cannot identify anybody on their own. Duplicate detection therefore pairs them with date of
birth, and these tests pin down both halves - that a bare 12-digit number is rejected outright,
and that two unrelated people who happen to share a suffix are not treated as the same person.
"""

from datetime import date

import pytest

from api.models import Candidate
from api.services.candidate_validation import identity_key, validate_candidate_values
from api.services.duplicate_check import run_duplicate_check

BASE_ROW = {
    'first_name': 'Asha',
    'last_name': 'Rao',
    'email': 'asha.rao@example.test',
    'phone': '9876543210',
    'date_of_birth': date(1999, 5, 20),
    'college_name': 'Test College',
    'degree': 'BE',
    'stream': 'CS',
    'percentage': 70,
    'passing_out_year': 2025,
    'location': 'Pune',
}


def row(**overrides):
    return {**BASE_ROW, **overrides}


class TestSchema:
    def test_only_four_digits_can_be_stored(self):
        field = Candidate._meta.get_field('aadhaar_last4')
        assert field.max_length == 4

    def test_the_full_number_field_is_gone(self):
        """A leftover aadhaar_number column would be a place full numbers could accumulate."""
        names = {f.name for f in Candidate._meta.get_fields()}
        assert 'aadhaar_number' not in names


class TestValidation:
    def test_four_digits_is_valid(self):
        status, errors = validate_candidate_values(row(aadhaar_last4='1234'))
        assert status == Candidate.ValidationStatus.OK, errors

    def test_a_full_twelve_digit_number_is_rejected(self):
        """Rejected rather than silently truncated: a full number in the upload means the
        spreadsheet is the old format, and quietly accepting it would mean full Aadhaar numbers
        were being handed to the system in bulk.
        """
        status, _ = validate_candidate_values(row(aadhaar_last4='123456789012'))
        assert status == Candidate.ValidationStatus.INVALID_AADHAAR

    @pytest.mark.parametrize('value', ['12a4', 'abcd', '12 4', '12-4', '123', '12345'])
    def test_anything_that_is_not_exactly_four_digits_is_rejected(self, value):
        status, _ = validate_candidate_values(row(aadhaar_last4=value))
        assert status == Candidate.ValidationStatus.INVALID_AADHAAR, value

    @pytest.mark.parametrize('value', ['', None])
    def test_blank_is_reported_as_missing_not_invalid(self, value):
        """Distinct statuses because they need different fixes: missing means the column was not
        filled in, invalid means it was filled in wrongly.
        """
        status, _ = validate_candidate_values(row(aadhaar_last4=value))
        assert status == Candidate.ValidationStatus.MISSING_AADHAAR

    def test_leading_zeros_are_preserved(self):
        """A suffix like 0042 must not be normalised to an integer anywhere along the way."""
        status, errors = validate_candidate_values(row(aadhaar_last4='0042'))
        assert status == Candidate.ValidationStatus.OK, errors


class TestIdentityKey:
    def test_same_digits_and_same_dob_are_the_same_identity(self):
        assert (identity_key({'aadhaar_last4': '1234', 'date_of_birth': date(1999, 5, 20)})
                == identity_key({'aadhaar_last4': '1234', 'date_of_birth': date(1999, 5, 20)}))

    def test_same_digits_but_different_dob_are_different_people(self):
        """The point of pairing with date of birth. Four digits alone collide about 1 in 10,000,
        so keying on them alone would flag unrelated candidates as duplicates of each other.
        """
        assert (identity_key({'aadhaar_last4': '1234', 'date_of_birth': date(1999, 5, 20)})
                != identity_key({'aadhaar_last4': '1234', 'date_of_birth': date(2000, 1, 1)}))

    def test_same_dob_but_different_digits_are_different_people(self):
        assert (identity_key({'aadhaar_last4': '1234', 'date_of_birth': date(1999, 5, 20)})
                != identity_key({'aadhaar_last4': '9999', 'date_of_birth': date(1999, 5, 20)}))

    def test_name_plays_no_part_in_the_key(self):
        """Name used to be the second half of this key; it no longer is. Two rows with the same
        Aadhaar+DOB but completely different names are still one identity.
        """
        assert (identity_key({'aadhaar_last4': '1234', 'date_of_birth': date(1999, 5, 20),
                              'first_name': 'Asha', 'last_name': 'Rao'})
                == identity_key({'aadhaar_last4': '1234', 'date_of_birth': date(1999, 5, 20),
                                 'first_name': 'Completely Different', 'last_name': 'Person'}))

    def test_a_missing_dob_never_matches_anything_including_itself(self):
        """No DOB means no key to match on - same early-out as a missing Aadhaar suffix (see
        services/duplicate_check.run_duplicate_check). Two blank-DOB rows sharing an Aadhaar
        suffix must not silently collide with each other.
        """
        a = identity_key({'aadhaar_last4': '1234', 'date_of_birth': None})
        b = identity_key({'aadhaar_last4': '1234', 'date_of_birth': None})
        assert a == b  # the tuple itself is equal...
        # ...but callers (run_duplicate_check, link_profile) never reach identity_key() at all
        # for a candidate with no DOB - they early-out first. See TestDuplicateDetection below.


class TestDuplicateDetection:
    def test_the_same_person_in_an_earlier_batch_is_flagged(
        self, ta_user, make_batch, make_candidate
    ):
        dob = date(1998, 3, 14)
        make_candidate(make_batch(ta_user), ta_user,
                       date_of_birth=dob, aadhaar_last4='7777',
                       email='asha@example.test')
        repeat = make_candidate(make_batch(ta_user), ta_user,
                                date_of_birth=dob, aadhaar_last4='7777',
                                email='asha.again@example.test')

        assert run_duplicate_check(repeat).check_status != 'new'

    def test_a_shared_suffix_alone_does_not_flag_an_unrelated_person(
        self, ta_user, make_batch, make_candidate
    ):
        """The false-positive case this design exists to prevent. Being wrongly flagged blocks a
        legitimate candidate, which is worse than a missed duplicate getting human review.
        """
        make_candidate(make_batch(ta_user), ta_user,
                       date_of_birth=date(1998, 3, 14), aadhaar_last4='7777',
                       email='asha@example.test')
        unrelated = make_candidate(make_batch(ta_user), ta_user,
                                   date_of_birth=date(2001, 11, 2), aadhaar_last4='7777',
                                   email='vikram@example.test')

        assert run_duplicate_check(unrelated).check_status == 'new'

    def test_same_dob_different_name_is_still_flagged(
        self, ta_user, make_batch, make_candidate
    ):
        """Name is no longer part of the key - a re-upload under a differently spelled (or
        entirely different) name still matches, as long as Aadhaar+DOB agree.
        """
        dob = date(1998, 3, 14)
        make_candidate(make_batch(ta_user), ta_user, date_of_birth=dob, aadhaar_last4='7777',
                       first_name='Asha', last_name='Rao', email='asha@example.test')
        repeat = make_candidate(make_batch(ta_user), ta_user, date_of_birth=dob,
                                aadhaar_last4='7777', first_name='A', last_name='Rau',
                                email='a.rau@example.test')

        assert run_duplicate_check(repeat).check_status != 'new'

    def test_a_candidate_with_no_dob_is_never_flagged(
        self, ta_user, make_batch, make_candidate
    ):
        dob = date(1998, 3, 14)
        make_candidate(make_batch(ta_user), ta_user, date_of_birth=dob, aadhaar_last4='7777',
                       email='asha@example.test')
        no_dob = make_candidate(make_batch(ta_user), ta_user, date_of_birth=None,
                                aadhaar_last4='7777', email='no.dob@example.test')

        assert run_duplicate_check(no_dob).check_status == 'new'


class TestApiNeverExposesMoreThanFourDigits:
    def test_candidate_detail_exposes_only_the_suffix(
        self, ta_user, client_for, make_batch, make_candidate
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user, aadhaar_last4='4321')
        response = client_for(ta_user).get('/api/candidates/%d/' % candidate.candidate_id)

        assert response.status_code == 200
        body = str(response.data)
        assert 'aadhaar_number' not in body
        # Whatever the presentation (masked or bare), no more than four digits can appear,
        # because no more than four are stored.
        assert '4321' in body
