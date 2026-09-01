"""One CandidateProfile per real person (by Aadhaar last 4 + name), aggregating that person's
Candidate rows across every batch they've appeared in - see api/services/candidate_profile.py.

Covers: profile creation/reuse on upload and on inline row edit ("recent entry wins"), the All
Candidates listing collapsing to one row per profile while a batch-scoped listing still shows
every row, and the candidate detail page's "other batches" history.
"""

import io

from openpyxl import Workbook

from api.models import Batch, CandidateProfile
from api.services.candidate_profile import link_profile
from api.services.excel_upload import stage_candidates_from_workbook


def _workbook_with_row(*row):
    wb = Workbook()
    ws = wb.active
    ws.append(['Name', 'Email', 'Mobile', 'Aadhaar Last 4 Digits', 'College Name', 'Degree',
              'Stream', 'Percentage', 'Passing Out Year', 'Location'])
    ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class TestProfileCreatedOnUpload:
    def test_first_upload_of_an_identity_creates_a_profile(self, ta_user, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        buf = _workbook_with_row('Asha Rao', 'asha@example.test', '9876543210',
                                 '5678', 'Test College', 'BE', 'CS', '75', '2025', 'Pune')

        created, *_ = stage_candidates_from_workbook(batch, buf, ta_user)

        assert len(created) == 1
        candidate = created[0]
        assert candidate.profile_id is not None
        assert candidate.profile.college_name == 'Test College'

    def test_a_later_batch_upload_of_the_same_identity_attaches_to_the_same_profile(
        self, ta_user, make_batch,
    ):
        first_batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        first_buf = _workbook_with_row('Asha Rao', 'asha@example.test', '9876543210',
                                       '5678', 'Old College', 'BE', 'CS', '70', '2024', 'Pune')
        first_created, *_ = stage_candidates_from_workbook(first_batch, first_buf, ta_user)
        profile_id = first_created[0].profile_id

        second_batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        second_buf = _workbook_with_row('Asha Rao', 'asha.new@example.test', '9876543210',
                                        '5678', 'New College', 'ME', 'IT', '85', '2025', 'Mumbai')
        second_created, *_ = stage_candidates_from_workbook(second_batch, second_buf, ta_user)

        assert second_created[0].profile_id == profile_id
        assert CandidateProfile.objects.filter(identity_key__startswith='5678:').count() == 1
        # "Recent entry wins" - the profile now reflects the SECOND upload's data.
        profile = CandidateProfile.objects.get(pk=profile_id)
        assert profile.college_name == 'New College'
        assert profile.email == 'asha.new@example.test'

    def test_a_row_with_no_aadhaar_never_gets_a_profile(self, ta_user, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        buf = _workbook_with_row('No Aadhaar', 'noaadhaar@example.test', '9876543210',
                                 '', 'Test College', 'BE', 'CS', '75', '2025', 'Pune')

        created, *_ = stage_candidates_from_workbook(batch, buf, ta_user)

        assert len(created) == 1
        assert created[0].profile_id is None


class TestProfileUpdatedOnRowEdit:
    def test_editing_a_staged_rows_college_updates_the_linked_profile(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        candidate = make_candidate(batch, ta_user, aadhaar_last4='5678', first_name='Asha',
                                   last_name='Rao', college_name='Old College')
        link_profile(candidate)
        profile_id = candidate.profile_id

        response = client_for(ta_user).patch(
            '/api/batches/%d/candidates/%d/' % (batch.batch_id, candidate.candidate_id),
            {'college_name': 'New College'}, format='json',
        )

        assert response.status_code == 200, response.data
        profile = CandidateProfile.objects.get(pk=profile_id)
        assert profile.college_name == 'New College'


class TestAllCandidatesListingDedupesByProfile:
    def test_no_batch_filter_returns_one_row_per_profile_showing_latest_batch(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        older_batch = make_batch(ta_user, batch_name='Older Batch')
        newer_batch = make_batch(ta_user, batch_name='Newer Batch')
        older = make_candidate(older_batch, ta_user, aadhaar_last4='5678', first_name='Asha',
                               last_name='Rao')
        link_profile(older)
        newer = make_candidate(newer_batch, ta_user, aadhaar_last4='5678', first_name='Asha',
                               last_name='Rao')
        link_profile(newer)

        response = client_for(ta_user).get('/api/candidates/?page_size=200')

        assert response.status_code == 200, response.data
        ids = [row['candidate_id'] for row in response.data['results']]
        assert newer.candidate_id in ids
        assert older.candidate_id not in ids

    def test_batch_filtered_listing_still_returns_every_row(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        older_batch = make_batch(ta_user, batch_name='Older Batch')
        newer_batch = make_batch(ta_user, batch_name='Newer Batch')
        older = make_candidate(older_batch, ta_user, aadhaar_last4='5678', first_name='Asha',
                               last_name='Rao')
        link_profile(older)
        newer = make_candidate(newer_batch, ta_user, aadhaar_last4='5678', first_name='Asha',
                               last_name='Rao')
        link_profile(newer)

        response = client_for(ta_user).get(
            '/api/candidates/?page_size=200&batch_id=%d' % older_batch.batch_id
        )

        assert response.status_code == 200, response.data
        ids = [row['candidate_id'] for row in response.data['results']]
        assert ids == [older.candidate_id]

    def test_a_candidate_with_no_profile_still_shows_individually(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        batch = make_batch(ta_user)
        candidate = make_candidate(batch, ta_user, aadhaar_last4='')

        response = client_for(ta_user).get('/api/candidates/?page_size=200')

        ids = [row['candidate_id'] for row in response.data['results']]
        assert candidate.candidate_id in ids


class TestCandidateDetailOtherBatches:
    def test_other_batches_lists_the_persons_other_memberships(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        older_batch = make_batch(ta_user, batch_name='Older Batch')
        newer_batch = make_batch(ta_user, batch_name='Newer Batch')
        older = make_candidate(older_batch, ta_user, aadhaar_last4='5678', first_name='Asha',
                               last_name='Rao')
        link_profile(older)
        newer = make_candidate(newer_batch, ta_user, aadhaar_last4='5678', first_name='Asha',
                               last_name='Rao')
        link_profile(newer)

        response = client_for(ta_user).get('/api/candidates/%d/' % newer.candidate_id)

        assert response.status_code == 200, response.data
        other_ids = [row['candidate_id'] for row in response.data['other_batches']]
        assert other_ids == [older.candidate_id]
        assert response.data['other_batches'][0]['batch_name'] == 'Older Batch'

    def test_a_candidate_with_no_profile_has_an_empty_other_batches_list(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        batch = make_batch(ta_user)
        candidate = make_candidate(batch, ta_user, aadhaar_last4='')

        response = client_for(ta_user).get('/api/candidates/%d/' % candidate.candidate_id)

        assert response.status_code == 200, response.data
        assert response.data['other_batches'] == []
