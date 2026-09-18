"""Editing a candidate's Aadhaar or date of birth must re-link their CandidateProfile.

All Candidates collapses to one row per CandidateProfile (services/access.dedupe_by_profile).
Aadhaar last 4 + date of birth is the key that decides which profile a row belongs to - and
Edit Candidate Details can change both. When the edit did not re-link, the row kept pointing at
the profile for the identity it USED to have, and the same real person appeared two or three
times in All Candidates, each under a different stale profile.

Reported against live data: three rows sharing Aadhaar 2737 and DOB 2003-08-26 sat under
profiles keyed 2334:2006-09-29, 2737:1992-09-05 and 2737:2003-08-26, so the de-duplication had
nothing to collapse them on. 25 rows were mis-linked that way in total.
"""
from datetime import date

import pytest

from api.models import Candidate, CandidateProfile
from api.services.access import dedupe_by_profile
from api.services.candidate_profile import link_profile

pytestmark = pytest.mark.django_db


class TestEditingTheIdentityKeyRelinksTheProfile:
    def test_correcting_a_mistyped_aadhaar_moves_the_row_to_the_right_profile(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        batch = make_batch(ta_user)
        candidate = make_candidate(batch, ta_user, aadhaar_last4='1111',
                                   date_of_birth=date(2003, 8, 26))
        link_profile(candidate)
        candidate.refresh_from_db()
        original_profile_id = candidate.profile_id

        client_for(ta_user).patch(
            '/api/candidates/%d/' % candidate.candidate_id,
            {'aadhaar_last4': '2737'}, format='json',
        )

        candidate.refresh_from_db()
        assert candidate.profile_id != original_profile_id
        assert candidate.profile.identity_key == '2737:2003-08-26'

    def test_correcting_a_mistyped_dob_moves_the_row_to_the_right_profile(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        batch = make_batch(ta_user)
        candidate = make_candidate(batch, ta_user, aadhaar_last4='2737',
                                   date_of_birth=date(1992, 9, 5))
        link_profile(candidate)

        client_for(ta_user).patch(
            '/api/candidates/%d/' % candidate.candidate_id,
            {'date_of_birth': '2003-08-26'}, format='json',
        )

        candidate.refresh_from_db()
        assert candidate.profile.identity_key == '2737:2003-08-26'

    def test_two_rows_corrected_onto_the_same_identity_collapse_to_one(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        """The reported bug, end to end: the same person across two batches, each row first
        uploaded under a different mistyped identity, then both corrected.
        """
        client = client_for(ta_user)
        rows = []
        for wrong_last4 in ('2334', '9999'):
            candidate = make_candidate(
                make_batch(ta_user), ta_user, aadhaar_last4=wrong_last4,
                date_of_birth=date(2006, 9, 29),
            )
            link_profile(candidate)
            rows.append(candidate)

        # Two distinct people as far as the system is concerned, so far.
        assert dedupe_by_profile(Candidate.objects.filter(
            candidate_id__in=[c.candidate_id for c in rows])).count() == 2

        for candidate in rows:
            client.patch('/api/candidates/%d/' % candidate.candidate_id,
                         {'aadhaar_last4': '2737', 'date_of_birth': '2003-08-26'},
                         format='json')

        assert dedupe_by_profile(Candidate.objects.filter(
            candidate_id__in=[c.candidate_id for c in rows])).count() == 1

    def test_all_candidates_shows_one_row_for_the_corrected_person(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        client = client_for(ta_user)
        for wrong_last4 in ('2334', '9999', '1234'):
            candidate = make_candidate(
                make_batch(ta_user), ta_user, aadhaar_last4=wrong_last4,
                date_of_birth=date(2006, 9, 29),
            )
            link_profile(candidate)
            client.patch('/api/candidates/%d/' % candidate.candidate_id,
                         {'aadhaar_last4': '2737', 'date_of_birth': '2003-08-26'},
                         format='json')

        # No batch_id, so this is the All Candidates listing - the screen that showed the
        # duplicates. Deliberately asserted through the real endpoint, not just the helper.
        response = client.get('/api/candidates/')

        assert response.status_code == 200, response.data
        matching = [r for r in response.data['results'] if r['aadhaar_last4'].endswith('2737')]
        assert len(matching) == 1

    def test_a_non_identity_edit_still_mirrors_onto_the_profile(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        # link_profile also mirrors the person-level fields, which is why the serializer calls it
        # unconditionally rather than only when the key changed.
        batch = make_batch(ta_user)
        candidate = make_candidate(batch, ta_user, aadhaar_last4='2737',
                                   date_of_birth=date(2003, 8, 26))
        link_profile(candidate)

        client_for(ta_user).patch('/api/candidates/%d/' % candidate.candidate_id,
                                  {'college_name': 'Corrected College'}, format='json')

        candidate.refresh_from_db()
        assert candidate.profile.college_name == 'Corrected College'

    def test_clearing_the_aadhaar_leaves_the_row_alone_rather_than_failing(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        # link_profile's early-out: nothing to key on means nothing to match against. The edit
        # must still save - some rows were uploaded with no Aadhaar at all.
        batch = make_batch(ta_user)
        candidate = make_candidate(batch, ta_user, aadhaar_last4='2737',
                                   date_of_birth=date(2003, 8, 26))
        link_profile(candidate)

        response = client_for(ta_user).patch(
            '/api/candidates/%d/' % candidate.candidate_id,
            {'aadhaar_last4': '', 'college_name': 'Still Saves'}, format='json',
        )

        assert response.status_code == 200, response.data
        candidate.refresh_from_db()
        assert candidate.college_name == 'Still Saves'

    def test_no_duplicate_profile_is_created_for_an_identity_that_already_exists(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        existing = make_candidate(make_batch(ta_user), ta_user, aadhaar_last4='2737',
                                  date_of_birth=date(2003, 8, 26))
        link_profile(existing)
        before = CandidateProfile.objects.count()

        other = make_candidate(make_batch(ta_user), ta_user, aadhaar_last4='1111',
                               date_of_birth=date(2003, 8, 26))
        link_profile(other)
        client_for(ta_user).patch('/api/candidates/%d/' % other.candidate_id,
                                  {'aadhaar_last4': '2737'}, format='json')

        other.refresh_from_db()
        existing.refresh_from_db()
        assert other.profile_id == existing.profile_id
        # The '1111' profile still exists but is now empty - orphans are inert, nothing reads a
        # profile except through a Candidate. What must NOT happen is a second '2737' profile.
        assert CandidateProfile.objects.filter(identity_key='2737:2003-08-26').count() == 1
        assert CandidateProfile.objects.count() == before + 1
