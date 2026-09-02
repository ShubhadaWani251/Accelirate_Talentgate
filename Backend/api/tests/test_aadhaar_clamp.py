"""A full-length Aadhaar number must never crash an upload or an inline row edit.

aadhaar_last4 is a database varchar(4), but nothing enforced that length before a write reached
it - the bulk upload and the inline row-edit both write straight to the ORM, bypassing any
serializer-level max_length check. A recruiter pasting a full 12-digit Aadhaar number (the format
every external HR export still uses) raised a raw DataError that rolled back the ENTIRE upload
transaction, discarding every other candidate in the same file - including, memorably, the
template's own bundled sample row, which shipped with a 12-digit example under a 4-digit column.
"""

import io

from django.db import transaction
from openpyxl import Workbook

from api.models import Batch, Candidate
from api.services.candidate_validation import clamp_aadhaar_to_last4
from api.services.excel_upload import generate_template_workbook, stage_candidates_from_workbook


class TestClampHelper:
    def test_a_full_number_keeps_only_the_last_four(self):
        assert clamp_aadhaar_to_last4('123456789012') == '9012'

    def test_a_value_already_short_is_unchanged(self):
        assert clamp_aadhaar_to_last4('1234') == '1234'
        assert clamp_aadhaar_to_last4('12') == '12'

    def test_blank_and_none_are_safe(self):
        assert clamp_aadhaar_to_last4('') == ''
        assert clamp_aadhaar_to_last4(None) == ''

    def test_matches_the_migrations_own_truncation_direction(self):
        """Migration 0013 truncated every existing full Aadhaar number in the database with
        RIGHT(...) - the last 4 digits, not the first 4. New data has to be clamped the same
        way, or the same person could get a different suffix depending on when their row was
        written.
        """
        assert clamp_aadhaar_to_last4('987654321234') == '1234'


def _workbook_with_row(*row):
    wb = Workbook()
    ws = wb.active
    ws.append(['Name', 'Email', 'Mobile', 'Aadhaar Last 4 Digits', 'Date of Birth (DD/MM/YYYY)',
              'College Name', 'Degree', 'Stream', 'Percentage', 'Passing Out Year', 'Location'])
    ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class TestBulkUploadSurvivesAFullAadhaarNumber:
    def test_the_bundled_template_uploads_successfully(self, ta_user, make_batch):
        """The exact regression: downloading the template and uploading it unmodified used to
        crash on its own bundled sample row.
        """
        batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        buf = io.BytesIO()
        generate_template_workbook().save(buf)
        buf.seek(0)

        with transaction.atomic():
            created, missing, staged, skipped = stage_candidates_from_workbook(batch, buf, ta_user)
            assert len(created) == 1
            assert len(created[0].aadhaar_last4) <= 4
            transaction.set_rollback(True)

    def test_a_row_with_a_full_twelve_digit_number_does_not_crash(self, ta_user, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        buf = _workbook_with_row('Asha Rao', 'asha@example.test', '9876543210',
                                 '198765432109', '15/06/2001',
                                 'Test College', 'BE', 'CS', '75', '2025', 'Pune')

        with transaction.atomic():
            created, missing, staged, skipped = stage_candidates_from_workbook(batch, buf, ta_user)
            assert len(created) == 1
            assert created[0].aadhaar_last4 == '2109'
            transaction.set_rollback(True)

    def test_a_valid_row_after_the_bad_one_is_not_lost(self, ta_user, make_batch):
        """The real cost of the crash: it took the WHOLE upload down with it, not just the one
        oversized row. Two rows in, the second must still land.
        """
        batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        wb = Workbook()
        ws = wb.active
        ws.append(['Name', 'Email', 'Mobile', 'Aadhaar Last 4 Digits', 'Date of Birth (DD/MM/YYYY)',
                  'College Name', 'Degree', 'Stream', 'Percentage', 'Passing Out Year', 'Location'])
        ws.append(['Asha Rao', 'asha@example.test', '9876543210', '198765432109', '15/06/2001',
                  'Test College', 'BE', 'CS', '75', '2025', 'Pune'])
        ws.append(['Vikram Shah', 'vikram@example.test', '9876543211', '5678', '02/11/2000',
                  'Test College', 'BE', 'CS', '80', '2025', 'Pune'])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        with transaction.atomic():
            created, missing, staged, skipped = stage_candidates_from_workbook(batch, buf, ta_user)
            assert len(created) == 2
            assert {c.aadhaar_last4 for c in created} == {'2109', '5678'}
            transaction.set_rollback(True)

    def test_the_clamped_value_still_goes_through_normal_validation(self, ta_user, make_batch):
        """The fix must not create a bypass - a well-formed 12-digit number clamps to a valid
        4-digit suffix and validates OK, same as if it had been typed as 4 digits directly.
        """
        from api.services.candidate_validation import revalidate_batch_candidates
        batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        buf = _workbook_with_row('Asha Rao', 'asha@example.test', '9876543210',
                                 '198765432109', '15/06/2001',
                                 'Test College', 'BE', 'CS', '75', '2025', 'Pune')

        with transaction.atomic():
            stage_candidates_from_workbook(batch, buf, ta_user)
            candidate = Candidate.objects.get(batch=batch)
            assert candidate.validation_status == Candidate.ValidationStatus.OK
            transaction.set_rollback(True)


class TestRowEditSurvivesAFullAadhaarNumber:
    def test_patching_a_full_number_clamps_instead_of_crashing(
        self, ta_user, client_for, make_batch, make_candidate
    ):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        candidate = make_candidate(batch, ta_user, aadhaar_last4='0000')

        response = client_for(ta_user).patch(
            '/api/batches/%d/candidates/%d/' % (batch.batch_id, candidate.candidate_id),
            {'aadhaar_last4': '198765432109'}, format='json',
        )

        assert response.status_code == 200, response.data
        candidate.refresh_from_db()
        assert candidate.aadhaar_last4 == '2109'

    def test_an_already_short_value_is_unaffected(
        self, ta_user, client_for, make_batch, make_candidate
    ):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        candidate = make_candidate(batch, ta_user, aadhaar_last4='0000')

        response = client_for(ta_user).patch(
            '/api/batches/%d/candidates/%d/' % (batch.batch_id, candidate.candidate_id),
            {'aadhaar_last4': '4321'}, format='json',
        )

        assert response.status_code == 200, response.data
        candidate.refresh_from_db()
        assert candidate.aadhaar_last4 == '4321'
