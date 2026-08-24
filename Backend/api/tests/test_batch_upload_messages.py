"""BatchUploadView must tell the truth about why an upload produced nothing.

Going back to Upload from Validate and re-submitting a file - even the exact same one - re-runs
duplicate detection against candidates already staged on this batch (services/excel_upload.py
seeds its dedup set from the batch's own existing rows, specifically so a second file added to
the same draft collapses against the first). If every row in the resubmitted file matches
something already there, the upload legitimately creates nothing - but the file plainly had
data rows, so telling the uploader "no data rows found in that file" was simply wrong about what
happened and left them thinking their spreadsheet was broken.
"""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook


def _workbook_with_rows(*rows):
    wb = Workbook()
    ws = wb.active
    ws.append(['Name', 'Email', 'Mobile', 'Aadhaar Last 4 Digits', 'College Name', 'Degree',
              'Stream', 'Percentage', 'Passing Out Year', 'Location'])
    for row in rows:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    # Named explicitly: BatchUploadView checks the filename extension before it ever looks at
    # the content, and a bare BytesIO carries no name at all.
    return SimpleUploadedFile(
        'candidates.xlsx', buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


def _upload(client, batch_id, buf):
    return client.post(
        '/api/batches/%d/upload/' % batch_id, {'file': buf}, format='multipart',
    )


class TestGenuinelyEmptyFile:
    def test_a_header_only_file_gets_the_original_message(self, ta_user, client_for, make_batch):
        batch = make_batch(ta_user, status='draft')
        buf = _workbook_with_rows()  # header row only, no data

        response = _upload(client_for(ta_user), batch.batch_id, buf)

        assert response.status_code == 400
        assert response.data['detail'] == 'No data rows found in that file.'
        assert 'skipped_duplicates' not in response.data


class TestEveryRowAlreadyOnTheBatch:
    def test_the_message_names_the_real_cause_not_an_empty_file(
        self, ta_user, client_for, make_batch
    ):
        batch = make_batch(ta_user, status='draft')
        client = client_for(ta_user)
        row = ('Asha Rao', 'asha@example.test', '9876543210', '1234',
              'Test College', 'BE', 'CS', '75', '2025', 'Pune')

        first = _upload(client, batch.batch_id, _workbook_with_rows(row))
        assert first.status_code == 201, first.data

        second = _upload(client, batch.batch_id, _workbook_with_rows(row))

        assert second.status_code == 400
        assert 'already on this' in second.data['detail']
        assert 'No data rows found' not in second.data['detail']
        assert second.data['skipped_duplicates']

    def test_the_skip_count_in_the_message_matches_the_file(self, ta_user, client_for, make_batch):
        batch = make_batch(ta_user, status='draft')
        client = client_for(ta_user)
        rows = [
            ('Asha Rao', 'asha@example.test', '9876543210', '1234',
             'Test College', 'BE', 'CS', '75', '2025', 'Pune'),
            ('Vikram Shah', 'vikram@example.test', '9876543211', '5678',
             'Test College', 'BE', 'CS', '80', '2025', 'Pune'),
        ]
        _upload(client, batch.batch_id, _workbook_with_rows(*rows))

        response = _upload(client, batch.batch_id, _workbook_with_rows(*rows))

        assert response.status_code == 400
        assert len(response.data['skipped_duplicates']) == 2
        assert '2 duplicate' in response.data['detail']

    def test_a_mix_of_new_and_already_staged_rows_is_not_this_case_at_all(
        self, ta_user, client_for, make_batch
    ):
        """Guards the boundary: this message is only for ALL rows being duplicates. One new row
        among the repeats must succeed normally, not trip the all-duplicates message.
        """
        batch = make_batch(ta_user, status='draft')
        client = client_for(ta_user)
        existing_row = ('Asha Rao', 'asha@example.test', '9876543210', '1234',
                        'Test College', 'BE', 'CS', '75', '2025', 'Pune')
        _upload(client, batch.batch_id, _workbook_with_rows(existing_row))

        new_row = ('Vikram Shah', 'vikram@example.test', '9876543211', '5678',
                  'Test College', 'BE', 'CS', '80', '2025', 'Pune')
        response = _upload(client, batch.batch_id, _workbook_with_rows(existing_row, new_row))

        assert response.status_code == 201, response.data
        assert response.data['rows_created'] == 1
