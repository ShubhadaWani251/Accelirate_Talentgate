"""Adding candidates to a batch that is already finalized and already inviting.

Previously the only way to add a candidate to a running drive was to create a whole separate
batch for them. BatchUploadView now accepts an upload on an In Progress batch too, through a
different path from the Draft wizard: there is no review-and-fix step to come, so a row either
arrives ready to be invited or is thrown back with its reasons. See
excel_upload.add_candidates_to_live_batch for why an invalid row must NOT be kept here - it
would be permanently uninvitable with nothing in the UI explaining why.
"""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from api.models import Batch, Candidate

pytestmark = pytest.mark.django_db

VALID_ROW = ('Asha Rao', 'asha@example.test', '9876543210', '1234', '15/06/2003',
             'Test College', 'BE', 'CS', '75', '2025', 'Pune')
# Blank email - fails validation, which is the whole point of this row.
INVALID_ROW = ('Vikram Shah', '', '9876543211', '5678', '20/08/2003',
               'Test College', 'BE', 'CS', '80', '2025', 'Pune')


def _workbook_with_rows(*rows):
    wb = Workbook()
    ws = wb.active
    ws.append(['Name', 'Email', 'Mobile', 'Aadhaar Last 4 Digits', 'Date of Birth (DD/MM/YYYY)',
              'College Name', 'Degree', 'Stream', 'Percentage', 'Passing Out Year', 'Location'])
    for row in rows:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return SimpleUploadedFile(
        'candidates.xlsx', buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


def _upload(client, batch_id, *rows):
    return client.post(
        '/api/batches/%d/upload/' % batch_id,
        {'file': _workbook_with_rows(*rows)}, format='multipart',
    )


class TestAddingToALiveBatch:
    def test_a_valid_row_is_added_and_awaits_an_invite(self, ta_user, client_for, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.IN_PROGRESS)

        response = _upload(client_for(ta_user), batch.batch_id, VALID_ROW)

        assert response.status_code == 201, response.data
        assert response.data['added_count'] == 1
        candidate = Candidate.objects.get(batch=batch, email='asha@example.test')
        # Not auto-invited: the TA still selects them and sends, exactly as for the original
        # cohort. Silently emailing an assessment link as a side effect of an upload would be a
        # surprising amount of consequence for one button.
        assert candidate.status == Candidate.Status.PENDING_INVITE

    def test_the_batch_candidate_count_is_updated(self, ta_user, client_for, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.IN_PROGRESS)

        _upload(client_for(ta_user), batch.batch_id, VALID_ROW)

        batch.refresh_from_db()
        assert batch.total_candidates == 1


class TestInvalidRowsAreRejectedNotKept:
    """The load-bearing difference from the Draft path."""

    def test_an_invalid_row_is_not_left_on_the_batch(self, ta_user, client_for, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.IN_PROGRESS)

        response = _upload(client_for(ta_user), batch.batch_id, INVALID_ROW)

        assert response.status_code == 201, response.data
        assert response.data['rejected_count'] == 1
        assert not Candidate.objects.filter(batch=batch).exists()

    def test_the_rejection_names_the_row_and_its_reasons(self, ta_user, client_for, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.IN_PROGRESS)

        response = _upload(client_for(ta_user), batch.batch_id, INVALID_ROW)

        rejected = response.data['rejected'][0]
        assert rejected['name'] == 'Vikram Shah'
        assert rejected['errors'], 'a rejected row must say why, or it cannot be corrected'

    def test_valid_rows_in_the_same_file_are_still_added(self, ta_user, client_for, make_batch):
        """One bad row must not cost the TA the other nine."""
        batch = make_batch(ta_user, status=Batch.Status.IN_PROGRESS)

        response = _upload(client_for(ta_user), batch.batch_id, VALID_ROW, INVALID_ROW)

        assert response.data['added_count'] == 1
        assert response.data['rejected_count'] == 1
        assert Candidate.objects.filter(batch=batch).count() == 1

    def test_a_corrected_reupload_adds_the_row_without_duplicating_the_first(
        self, ta_user, client_for, make_batch
    ):
        """The intended recovery: fix the sheet, upload the whole thing again. The already-added
        row must collapse as a duplicate rather than being added twice.
        """
        batch = make_batch(ta_user, status=Batch.Status.IN_PROGRESS)
        client = client_for(ta_user)
        _upload(client, batch.batch_id, VALID_ROW, INVALID_ROW)

        corrected = ('Vikram Shah', 'vikram@example.test', '9876543211', '5678', '20/08/2003',
                     'Test College', 'BE', 'CS', '80', '2025', 'Pune')
        response = _upload(client, batch.batch_id, VALID_ROW, corrected)

        assert response.data['added_count'] == 1
        assert len(response.data['skipped_duplicates']) == 1
        assert Candidate.objects.filter(batch=batch).count() == 2


class TestClosedBatchesStillRefuseUploads:
    @pytest.mark.parametrize('batch_status', [Batch.Status.COMPLETED, Batch.Status.CANCELLED])
    def test_a_closed_batch_is_refused(self, ta_user, client_for, make_batch, batch_status):
        batch = make_batch(ta_user, status=batch_status)

        response = _upload(client_for(ta_user), batch.batch_id, VALID_ROW)

        assert response.status_code == 400
        assert not Candidate.objects.filter(batch=batch).exists()
