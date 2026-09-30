"""services/aadhaar_pdf.py - accepting the official e-Aadhaar PDF, not just a photo.

Most candidates hold their Aadhaar as the PDF UIDAI hands them, so refusing PDFs forced them to
photograph a document they already had in better quality than the photo would be. Two behaviours
carry the weight here: the PDF must be converted to an image BEFORE anything is stored (nothing
downstream - blob storage, the QR/OCR pipeline, the TA's evidence panel - should ever see a
PDF), and an unopenable one must fail with a message the candidate can act on rather than a 500.
"""
import datetime
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from api.models import Question, QuestionBankSection
from api.services import aadhaar_pdf

pytestmark = pytest.mark.django_db


# A genuine, minimal, uncompressed PDF. Handwritten rather than generated so the test has no
# dependency of its own, and so it stays readable as "this is what a one-page PDF is".
MINIMAL_PDF = b'''%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 150]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 64>>stream
BT /F1 16 Tf 20 60 Td (Government of India) Tj ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
trailer<</Root 1 0 R>>'''


class TestPdfRendering:
    def test_a_plain_pdf_renders_to_png_bytes(self):
        png = aadhaar_pdf.pdf_to_png_bytes(MINIMAL_PDF)

        # PNG magic number - the point is that what comes back is an IMAGE, since everything
        # downstream (cv2.imdecode, blob storage's content type, the evidence panel) assumes one.
        assert png.startswith(b'\x89PNG\r\n\x1a\n')

    def test_the_rendered_image_is_large_enough_to_ocr(self):
        """Rendered at 3x rather than 1:1 - a 72dpi rasterisation of a card is not something
        OCR can read, which would make the whole feature technically working and practically
        useless.
        """
        import cv2
        import numpy as np

        png = aadhaar_pdf.pdf_to_png_bytes(MINIMAL_PDF)
        image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)

        assert image.shape[1] >= 600, 'a 300pt-wide page should render well above 300px'

    def test_an_unreadable_file_raises_a_candidate_safe_error(self):
        with pytest.raises(aadhaar_pdf.AadhaarPdfError) as exc:
            aadhaar_pdf.pdf_to_png_bytes(b'this is not a pdf')

        # No stack trace, no library jargon - the candidate is mid-exam and needs to know what
        # to do next, which is "upload a photo instead".
        assert 'photo' in str(exc.value).lower()

    def test_a_wrong_password_is_reported_not_crashed(self):
        """Passwords that don't work must fall through to the same actionable message, not an
        exception - an e-Aadhaar whose name on file differs from the name on the card lands here.
        """
        with pytest.raises(aadhaar_pdf.AadhaarPdfError):
            aadhaar_pdf.pdf_to_png_bytes(b'%PDF-1.4 truncated garbage', ['WRONG2003'])


class TestPasswordDerivation:
    """UIDAI's documented e-Aadhaar password is the first 4 letters of the name in CAPITALS plus
    the birth year. Deriving it means the candidate is never asked to work that out mid-exam.
    """

    def _candidate(self, make_batch, make_candidate, ta_user, **fields):
        return make_candidate(make_batch(ta_user), ta_user, **fields)

    def test_it_follows_the_documented_uidai_format(
        self, ta_user, make_batch, make_candidate
    ):
        candidate = self._candidate(
            make_batch, make_candidate, ta_user,
            first_name='Asha', last_name='Rao', date_of_birth=datetime.date(2003, 6, 15),
        )

        assert 'ASHA2003' in aadhaar_pdf.candidate_pdf_passwords(candidate)

    def test_a_short_first_name_still_yields_the_full_name_variant(
        self, ta_user, make_batch, make_candidate
    ):
        """'Raj Kumar' has a 3-letter first name, so the 4-letter rule has to draw from the
        full name - RAJK - which is exactly what UIDAI does.
        """
        candidate = self._candidate(
            make_batch, make_candidate, ta_user,
            first_name='Raj', last_name='Kumar', date_of_birth=datetime.date(2002, 1, 20),
        )

        assert 'RAJK2002' in aadhaar_pdf.candidate_pdf_passwords(candidate)

    def test_no_date_of_birth_means_no_derivable_password(
        self, ta_user, make_batch, make_candidate
    ):
        candidate = self._candidate(
            make_batch, make_candidate, ta_user,
            first_name='Asha', last_name='Rao', date_of_birth=None,
        )

        assert aadhaar_pdf.candidate_pdf_passwords(candidate) == []


class TestPdfUploadThroughTheCaptureEndpoint:
    @pytest.fixture
    def small_invitation(self, ta_user, make_batch, make_candidate, make_invitation):
        section = QuestionBankSection.objects.get_or_create(
            section_key='logical',
            defaults={'section_name': 'Logical & Analytical Reasoning'},
        )[0]
        Question.objects.create(
            question_code='Q-AADHAAR-PDF-1', section=section, question_text='2 + 2 = ?',
            option_a='3', option_b='4', option_c='5', option_d='6', correct_option='B',
            difficulty=Question.Difficulty.EASY,
        )
        batch = make_batch(ta_user, logical_questions=1, quantitative_questions=0,
                           verbal_questions=0, programming_questions=0)
        candidate = make_candidate(
            batch, ta_user, aadhaar_last4='2346', date_of_birth=datetime.date(2003, 6, 15),
        )
        return make_invitation(candidate, ta_user)

    def _capture_pdf(self, api_client, token, pdf_bytes):
        return api_client.post(
            f'/api/exam/token/{token}/identity/aadhaar/',
            {'id_photo': SimpleUploadedFile(
                'eaadhaar.pdf', pdf_bytes, content_type='application/pdf',
            )},
            format='multipart',
        )

    def test_a_pdf_upload_is_refused(self, api_client, small_invitation, settings):
        """PDF is no longer an accepted format for the Aadhaar capture - JPEG and PNG only.

        Removed on request. The front of the card, photographed or screenshotted, is what
        verification reads, and a second accepted format doubled the ways a capture could arrive
        unreadable. The endpoint is what enforces it: the file input's `accept` attribute only
        filters the picker's default view, and every OS picker offers an "All Files" escape, so
        a client can always send whatever it likes.
        """
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        settings.AADHAAR_VERIFICATION_ENABLED = True
        token = small_invitation.unique_link_token
        api_client.post(f'/api/exam/token/{token}/verify-email/',
                        {'email': small_invitation.candidate.email})

        response = self._capture_pdf(api_client, token, MINIMAL_PDF)

        assert response.status_code == 400, response.data
        assert 'JPEG or PNG' in response.data['detail']

    def test_a_refused_pdf_stores_nothing_and_costs_no_attempt(
        self, api_client, small_invitation, settings
    ):
        """The rejection happens before any state changes, which is what makes it safe to retry.

        validate_identity_photo runs ahead of start_or_resume_attempt, so a candidate who picks
        the wrong file has not burned one of their AADHAAR_CAPTURE_MAX_ATTEMPTS retries and has
        nothing stored against them - they simply pick a different file.
        """
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        settings.AADHAAR_VERIFICATION_ENABLED = True
        token = small_invitation.unique_link_token
        api_client.post(f'/api/exam/token/{token}/verify-email/',
                        {'email': small_invitation.candidate.email})

        self._capture_pdf(api_client, token, MINIMAL_PDF)

        from api.models import ExamAttempt
        assert not ExamAttempt.objects.filter(invitation=small_invitation).exists()

    @pytest.mark.parametrize('filename, content_type', [
        ('scan.pdf', 'application/pdf'),
        ('aadhaar.docx',
         'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
        ('card.heic', 'image/heic'),
        ('card.gif', 'image/gif'),
        ('nothing.txt', 'text/plain'),
    ])
    def test_any_format_that_is_not_jpeg_or_png_is_refused(
        self, api_client, small_invitation, settings, filename, content_type
    ):
        """Parametrised rather than PDF-only because PDF is not special here - it is simply the
        one candidates reach for most, the official e-Aadhaar being one. HEIC earns its row too:
        it is what an iPhone produces by default, so it is the likeliest accidental upload after
        a PDF, and it has never been accepted.
        """
        settings.AZURE_STORAGE_CONNECTION_STRING = ''
        settings.DEBUG = True
        settings.AADHAAR_VERIFICATION_ENABLED = True
        token = small_invitation.unique_link_token
        api_client.post(f'/api/exam/token/{token}/verify-email/',
                        {'email': small_invitation.candidate.email})

        response = api_client.post(
            f'/api/exam/token/{token}/identity/aadhaar/',
            {'id_photo': SimpleUploadedFile(filename, b'bytes', content_type=content_type)},
            format='multipart',
        )

        assert response.status_code == 400, response.data
        assert 'JPEG or PNG' in response.data['detail']
        # No "or a PDF" tail any more - the message has to name only what is actually accepted.
        assert 'PDF' not in response.data['detail']
