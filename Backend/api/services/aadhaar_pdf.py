"""Converts a candidate-uploaded Aadhaar PDF into a PNG image the rest of the pipeline can read.

Candidates overwhelmingly have their Aadhaar as a PDF, not a photo: the official copy from the
UIDAI site (and the mAadhaar app) downloads as an e-Aadhaar PDF, so "upload your Aadhaar" and
"upload an image" are not the same request. Refusing PDFs meant asking every such candidate to
screenshot or photograph a document they already had in a perfectly readable digital form -
usually producing a worse image than the PDF renders, right before an OCR step whose accuracy
depends on exactly that.

Two things make this more than a file-format conversion:

1. AN e-AADHAAR PDF IS PASSWORD-PROTECTED. UIDAI encrypts it with a documented, derivable
   password: the first four letters of the holder's name in CAPITALS followed by their birth
   year (e.g. ASHA2003). We already hold both values on the Candidate row, so the password can
   be derived rather than demanded from the candidate - who, in the middle of a proctored exam
   with their clock running, should not be asked to work out a password format. If the derived
   candidates all fail the candidate is told plainly to upload a photo instead, because the
   alternative is a silent failure they cannot act on.

2. THE RENDERED IMAGE REPLACES THE PDF ENTIRELY. What gets stored as evidence and fed to
   services/aadhaar.py is the PNG, never the original PDF. The QR/OCR pipeline decodes images
   (cv2.imdecode), and a TA opening the evidence panel should see the card, not download an
   encrypted document they in turn cannot open.

PDFium (via pypdfium2, self-contained wheels - no system libraries, which matters on the
App Service runtime that has no apt-get) only rasterizes here: no JavaScript, no form actions,
one page. That is the same engine Chrome renders PDFs with, and rendering untrusted input is
inherently more surface than decoding a JPEG - bounded deliberately to a single page at a fixed
scale, with any failure surfacing as a message to the candidate rather than an exception.
"""

import io
import logging

import pypdfium2 as pdfium

logger = logging.getLogger(__name__)

PDF_CONTENT_TYPES = frozenset({'application/pdf'})

# Only ever the first page. The Aadhaar card itself is on page 1 of an e-Aadhaar; later pages
# are the address/offline-verification sections, and rendering them would just hand the OCR
# step more text to be ambiguous about.
_PAGE_INDEX = 0

# 72dpi x 3 puts an A4 page around 1785px on its long side - comfortably above the detail OCR
# needs, and just under services/aadhaar.py's own 1600px downscale cap, so the image arrives at
# roughly the resolution that module wants anyway rather than being rendered huge and shrunk.
_RENDER_SCALE = 3


class AadhaarPdfError(Exception):
    """Raised with a message safe to show the candidate directly."""


def is_pdf_upload(content_type):
    return (content_type or '').split(';')[0].strip().lower() in PDF_CONTENT_TYPES


def candidate_pdf_passwords(candidate):
    """Passwords worth trying for this candidate's e-Aadhaar, most likely first.

    UIDAI's documented format is the first 4 letters of the name in CAPITALS + birth year.
    "Name" there is the name printed on the Aadhaar card, which is not guaranteed to match the
    name a recruiter typed into a spreadsheet - so both the full name and the first name are
    tried, covering the common case where the sheet holds "Asha Rao" but the card reads "Asha
    Kumari Rao" (and vice versa). An empty list is returned when either half is missing, which
    just means an encrypted PDF cannot be opened for this candidate.
    """
    if not candidate.date_of_birth:
        return []
    year = candidate.date_of_birth.year
    seeds = [candidate.full_name or '', candidate.first_name or '']
    passwords = []
    for seed in seeds:
        letters = ''.join(ch for ch in seed if ch.isalpha())
        if len(letters) >= 4:
            attempt = f'{letters[:4].upper()}{year}'
            if attempt not in passwords:
                passwords.append(attempt)
    return passwords


def pdf_to_png_bytes(pdf_bytes, passwords=()):
    """Render page 1 of a PDF to PNG bytes.

    `passwords` is tried in order, after an unencrypted open. Raises AadhaarPdfError with a
    candidate-facing message if the document cannot be opened or has no pages.
    """
    document = None
    # None first: an unencrypted PDF (a scan, or a print-to-PDF) needs no password at all, and
    # is the case that must keep working regardless of what we can derive.
    for password in (None, *passwords):
        try:
            document = pdfium.PdfDocument(io.BytesIO(pdf_bytes), password=password)
            break
        except pdfium.PdfiumError:
            continue

    if document is None:
        raise AadhaarPdfError(
            'That PDF could not be opened - it looks password-protected, and the password '
            'could not be determined from your details. Please upload a photo or screenshot '
            'of your Aadhaar card instead.'
        )

    try:
        if len(document) == 0:
            raise AadhaarPdfError(
                'That PDF appears to be empty. Please upload a photo of your Aadhaar card '
                'instead.'
            )
        page = document[_PAGE_INDEX]
        image = page.render(scale=_RENDER_SCALE).to_pil()
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return buffer.getvalue()
    except AadhaarPdfError:
        raise
    except Exception as exc:  # noqa: BLE001 - any render failure is the candidate's file
        logger.exception('Failed to render an uploaded Aadhaar PDF')
        raise AadhaarPdfError(
            'That PDF could not be read. Please upload a photo of your Aadhaar card instead.'
        ) from exc
