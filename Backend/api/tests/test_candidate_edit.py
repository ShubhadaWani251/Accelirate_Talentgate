from datetime import date


class TestEditCandidateDetailsSavesAadhaarAndDob:
    """Edit Candidate Details (Frontend/EditCandidateModal.jsx) added aadhaar_last4/date_of_birth
    as editable fields - see CandidateUpdateSerializer. These confirm the PATCH actually persists
    both to the database (not just accepts them), and that the fix for the blank-DOB save failure
    this uncovered (an empty string isn't a valid date, unlike the DB's stored NULL) holds.
    """

    def test_patching_aadhaar_and_dob_persists_to_the_database(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        batch = make_batch(ta_user)
        candidate = make_candidate(batch, ta_user, aadhaar_last4='1111',
                                   date_of_birth=date(1995, 6, 1))

        response = client_for(ta_user).patch(
            '/api/candidates/%d/' % candidate.candidate_id,
            {'aadhaar_last4': '9999', 'date_of_birth': '1998-03-14'}, format='json',
        )

        assert response.status_code == 200, response.data
        candidate.refresh_from_db()
        assert candidate.aadhaar_last4 == '9999'
        assert candidate.date_of_birth == date(1998, 3, 14)

    def test_a_candidate_with_a_blank_aadhaar_and_dob_can_still_be_edited(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        """Regression test: the frontend now always sends aadhaar_last4/date_of_birth, even for
        a row uploaded before either field was captured (blank/'' and None respectively). Before
        buildPayload() coerced an empty date_of_birth to null, this 400'd on ANY edit to such a
        row - even one touching only, say, college_name.
        """
        batch = make_batch(ta_user)
        candidate = make_candidate(batch, ta_user, aadhaar_last4='', date_of_birth=None)

        response = client_for(ta_user).patch(
            '/api/candidates/%d/' % candidate.candidate_id,
            {'aadhaar_last4': '', 'date_of_birth': None, 'college_name': 'New College'},
            format='json',
        )

        assert response.status_code == 200, response.data
        candidate.refresh_from_db()
        assert candidate.college_name == 'New College'
        assert candidate.date_of_birth is None
