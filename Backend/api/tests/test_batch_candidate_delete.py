"""BatchCandidateDeleteView - POST /api/batches/<id>/candidates/delete/.

Covers the existing explicit-id-list mode (previously untested) and the new `clear_all` mode,
which discards every row currently staged on a Draft batch - added so BatchWizard's "Upload
another file" can start a genuinely fresh upload instead of comparing the new file against
whatever an abandoned first attempt already staged (see services/excel_upload.py's
seen_identity/seen_email, seeded from every row already on the batch).
"""

from api.models import Batch, Candidate


class TestExplicitIdList:
    def test_deletes_only_the_given_rows(self, ta_user, client_for, make_batch, make_candidate):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        keep = make_candidate(batch, ta_user, aadhaar_last4='1111')
        remove = make_candidate(batch, ta_user, aadhaar_last4='2222')

        response = client_for(ta_user).post(
            '/api/batches/%d/candidates/delete/' % batch.batch_id,
            {'candidate_ids': [remove.candidate_id]}, format='json',
        )

        assert response.status_code == 200, response.data
        assert response.data['deleted_count'] == 1
        remaining_ids = {c.candidate_id for c in Candidate.objects.filter(batch=batch)}
        assert remaining_ids == {keep.candidate_id}

    def test_an_empty_list_is_rejected(self, ta_user, client_for, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT)

        response = client_for(ta_user).post(
            '/api/batches/%d/candidates/delete/' % batch.batch_id,
            {'candidate_ids': []}, format='json',
        )

        assert response.status_code == 400


class TestClearAll:
    def test_removes_every_staged_candidate_regardless_of_id(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        make_candidate(batch, ta_user, aadhaar_last4='1111')
        make_candidate(batch, ta_user, aadhaar_last4='2222')
        make_candidate(batch, ta_user, aadhaar_last4='3333')

        response = client_for(ta_user).post(
            '/api/batches/%d/candidates/delete/' % batch.batch_id,
            {'clear_all': True}, format='json',
        )

        assert response.status_code == 200, response.data
        assert response.data['deleted_count'] == 3
        assert Candidate.objects.filter(batch=batch).count() == 0

    def test_a_second_upload_after_clearing_does_not_see_the_first_uploads_rows(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        """The actual regression: re-uploading the SAME identity after a clear must be treated
        as new, not skipped as a duplicate of a row that no longer exists.
        """
        import io
        from openpyxl import Workbook
        from api.services.excel_upload import stage_candidates_from_workbook

        batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        make_candidate(batch, ta_user, aadhaar_last4='5678', first_name='Asha', last_name='Rao')

        client_for(ta_user).post(
            '/api/batches/%d/candidates/delete/' % batch.batch_id,
            {'clear_all': True}, format='json',
        )

        wb = Workbook()
        ws = wb.active
        ws.append(['Name', 'Email', 'Mobile', 'Aadhaar Last 4 Digits', 'College Name', 'Degree',
                  'Stream', 'Percentage', 'Passing Out Year', 'Location'])
        ws.append(['Asha Rao', 'asha@example.test', '9876543210', '5678',
                  'Test College', 'BE', 'CS', '75', '2025', 'Pune'])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        batch.refresh_from_db()
        created, missing, staged, skipped = stage_candidates_from_workbook(batch, buf, ta_user)

        assert len(skipped) == 0
        assert len(created) == 1

    def test_empty_batch_clears_without_error(self, ta_user, client_for, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT)

        response = client_for(ta_user).post(
            '/api/batches/%d/candidates/delete/' % batch.batch_id,
            {'clear_all': True}, format='json',
        )

        assert response.status_code == 200, response.data
        assert response.data['deleted_count'] == 0

    def test_refuses_once_invites_have_been_sent(
        self, ta_user, client_for, make_batch, make_candidate, make_invitation,
    ):
        batch = make_batch(ta_user, status=Batch.Status.IN_PROGRESS)
        candidate = make_candidate(batch, ta_user)
        make_invitation(candidate, ta_user)

        response = client_for(ta_user).post(
            '/api/batches/%d/candidates/delete/' % batch.batch_id,
            {'clear_all': True}, format='json',
        )

        assert response.status_code == 400
        assert Candidate.objects.filter(batch=batch).count() == 1
