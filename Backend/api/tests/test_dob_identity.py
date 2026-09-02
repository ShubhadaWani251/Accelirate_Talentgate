"""Date of Birth: parsing, validation, and its role as half of the identity key.

DD/MM/YYYY is the one format used everywhere it's typed - the upload template and every edit
form (see services/candidate_validation.parse_dob_text). Covers the parser's accepted formats,
the new required-field validation, and that editing DOB (not just Aadhaar) on a staged row
re-runs the duplicate check and re-links the shared profile - the fix for "data and status
should be updated if I update anything in the review page."
"""

from datetime import date, timedelta

from django.utils import timezone

from api.models import Batch, CandidateProfile
from api.services.candidate_history import build_candidate_history
from api.services.candidate_validation import parse_dob_text, validate_candidate_values
from api.services.duplicate_check import run_duplicate_check


class TestParseDobText:
    def test_the_documented_format(self):
        assert parse_dob_text('15/06/2001') == date(2001, 6, 15)

    def test_the_hyphenated_variant(self):
        assert parse_dob_text('15-06-2001') == date(2001, 6, 15)

    def test_what_a_native_excel_date_cell_stringifies_to(self):
        """openpyxl hands a date-formatted cell back as a datetime object, which
        excel_upload._cell_to_text renders via str() - '2001-06-15 00:00:00' for a datetime,
        '2001-06-15' for a plain date. Both must still parse.
        """
        assert parse_dob_text('2001-06-15 00:00:00') == date(2001, 6, 15)
        assert parse_dob_text('2001-06-15') == date(2001, 6, 15)

    def test_blank_and_none_are_safe(self):
        assert parse_dob_text('') is None
        assert parse_dob_text(None) is None

    def test_garbage_does_not_raise(self):
        assert parse_dob_text('not a date') is None
        assert parse_dob_text('31/02/2001') is None  # no such day


class TestDobValidation:
    BASE = {
        'first_name': 'Asha', 'last_name': 'Rao', 'email': 'asha@example.test',
        'phone': '9876543210', 'aadhaar_last4': '1234', 'college_name': 'Test College',
        'degree': 'BE', 'stream': 'CS', 'percentage': 70, 'passing_out_year': 2025,
        'location': 'Pune',
    }

    def _row(self, **overrides):
        return {**self.BASE, **overrides}

    def test_missing_is_reported_as_missing_not_invalid(self):
        status, errors = validate_candidate_values(self._row(date_of_birth=None), raw={})
        assert status == 'missing_dob', errors

    def test_unparseable_raw_text_is_invalid(self):
        status, errors = validate_candidate_values(
            self._row(date_of_birth=None), raw={'date_of_birth': 'not a date'},
        )
        assert status == 'invalid_dob', errors

    def test_a_valid_dob_passes(self):
        status, errors = validate_candidate_values(
            self._row(date_of_birth=date(1999, 5, 20)), raw={'date_of_birth': '20/05/1999'},
        )
        assert status == 'ok', errors

    def test_a_future_date_is_rejected(self):
        future = timezone.now().date() + timedelta(days=1)
        status, errors = validate_candidate_values(
            self._row(date_of_birth=future), raw={'date_of_birth': future.strftime('%d/%m/%Y')},
        )
        assert status == 'invalid_dob', errors

    def test_an_implausibly_old_date_is_rejected(self):
        status, errors = validate_candidate_values(
            self._row(date_of_birth=date(1900, 1, 1)), raw={'date_of_birth': '01/01/1900'},
        )
        assert status == 'invalid_dob', errors


class TestReviewStepEditRefreshesStatus:
    """The reported bug: editing a staged row on the Review step must re-run the duplicate
    check and the profile link when the edit actually changes the identity (Aadhaar or DOB) -
    not just when Aadhaar changes, and not silently do nothing for everything else.
    """

    def test_editing_dob_alone_re_runs_the_duplicate_check(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        dob = date(1998, 3, 14)
        # An existing candidate elsewhere in the system sharing the identity the edit below is
        # about to adopt - run_duplicate_check matches against any Candidate row regardless of
        # its own batch's status, so one is enough.
        other_batch = make_batch(ta_user, status=Batch.Status.IN_PROGRESS)
        make_candidate(other_batch, ta_user, aadhaar_last4='7777', date_of_birth=dob)

        batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        candidate = make_candidate(batch, ta_user, aadhaar_last4='9999', date_of_birth=date(2000, 1, 1))

        response = client_for(ta_user).patch(
            '/api/batches/%d/candidates/%d/' % (batch.batch_id, candidate.candidate_id),
            {'aadhaar_last4': '7777', 'date_of_birth': dob.strftime('%d/%m/%Y')}, format='json',
        )

        assert response.status_code == 200, response.data
        row = next(r for r in response.data['rows'] if r['candidate_id'] == candidate.candidate_id)
        assert row['duplicate_status'] != 'new'

    def test_editing_dob_updates_the_linked_profile(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        candidate = make_candidate(batch, ta_user, aadhaar_last4='5678',
                                   date_of_birth=date(1999, 1, 1), college_name='Old College')

        response = client_for(ta_user).patch(
            '/api/batches/%d/candidates/%d/' % (batch.batch_id, candidate.candidate_id),
            {'date_of_birth': '20/05/1999', 'college_name': 'New College'}, format='json',
        )

        assert response.status_code == 200, response.data
        candidate.refresh_from_db()
        assert candidate.date_of_birth == date(1999, 5, 20)
        assert candidate.profile_id is not None
        profile = CandidateProfile.objects.get(pk=candidate.profile_id)
        assert profile.college_name == 'New College'
        assert profile.date_of_birth == date(1999, 5, 20)

    def test_editing_an_unrelated_field_does_not_re_run_the_duplicate_check(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        candidate = make_candidate(batch, ta_user, aadhaar_last4='5678',
                                   date_of_birth=date(1999, 1, 1))
        original_check_count = candidate.duplicate_checks.count()

        response = client_for(ta_user).patch(
            '/api/batches/%d/candidates/%d/' % (batch.batch_id, candidate.candidate_id),
            {'college_name': 'New College'}, format='json',
        )

        assert response.status_code == 200, response.data
        assert candidate.duplicate_checks.count() == original_check_count


class TestHistoryFollowsOnlyTheLatestCheck:
    """Reported live: the History modal kept showing a cross-batch match after a Review-step
    edit had already corrected the DOB away from it - because run_duplicate_check always
    records a NEW DuplicateCheck rather than updating the old one, and build_candidate_history
    used to fold in matches from EVERY check ever run for a row, not just the current one. Now
    it only ever follows the latest, same as the duplicate-status pill already did.
    """

    def test_a_genuine_match_appears_in_history(self, ta_user, make_batch, make_candidate):
        dob = date(1998, 3, 14)
        other = make_candidate(make_batch(ta_user), ta_user, aadhaar_last4='7777', date_of_birth=dob)
        candidate = make_candidate(make_batch(ta_user), ta_user, aadhaar_last4='7777', date_of_birth=dob)
        run_duplicate_check(candidate)

        events = build_candidate_history(candidate)

        assert any(e['batch_name'] == other.batch.batch_name for e in events)

    def test_a_correction_that_clears_the_match_removes_it_from_history(
        self, ta_user, make_batch, make_candidate,
    ):
        dob = date(1998, 3, 14)
        other = make_candidate(make_batch(ta_user), ta_user, aadhaar_last4='7777', date_of_birth=dob)
        candidate = make_candidate(make_batch(ta_user), ta_user, aadhaar_last4='7777', date_of_birth=dob)
        # First check: genuinely matches (mirrors what happened before a TA's correction).
        run_duplicate_check(candidate)
        assert any(e['batch_name'] == other.batch.batch_name
                   for e in build_candidate_history(candidate))

        # The TA corrects the DOB - a typo, it turns out - to one that does NOT match `other`.
        # This creates a SECOND, newer DuplicateCheck row rather than replacing the first.
        candidate.date_of_birth = date(2000, 1, 1)
        candidate.save(update_fields=['date_of_birth'])
        run_duplicate_check(candidate)

        events = build_candidate_history(candidate)

        assert not any(e['batch_name'] == other.batch.batch_name for e in events)
        # The candidate's own events are still there - only the stale cross-batch match is gone.
        assert any(e['event'] == 'Uploaded' and e['batch_name'] == candidate.batch.batch_name
                   for e in events)
