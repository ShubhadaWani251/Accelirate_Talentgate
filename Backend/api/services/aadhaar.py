"""Automated Aadhaar identity verification for the exam-time identity-capture flow.

Gated end-to-end by settings.AADHAAR_VERIFICATION_ENABLED (default off) - nothing in this module
does anything until that flag is explicitly turned on. Once it IS on, this deliberately gates exam
start: identity capture only completes once one of verify_identity_photo / try_ocr_inline /
run_ocr_fallback has recorded a MATCH (see views.exam.ExamIdentityCaptureView's own check), and a
candidate who hasn't matched yet retries the Aadhaar photo - as many times as it takes - rather
than being waved through after some cap. There is deliberately no "proceed anyway" path here.

What every public function below still guarantees is narrower than "never blocks": none of them
ever RAISES into the identity-capture request itself - a bad image, a corrupt QR, an OCR engine
failure all degrade to leaving the verdict at PENDING (a 200 with "keep trying", never a 500),
matching api/services/seb.py's same crash-safety guarantee for SEB verification. A PENDING or
MISMATCH verdict is still a real, intentional block on progressing, by policy.

Two paths, matching how differently they cost:
  - FAST (verify_identity_photo): decode the QR on the captured id_photo. A legacy (pre-Secure-QR)
    Aadhaar card's QR is a plain, unsigned XML payload with the Aadhaar number (and usually a date
    of birth, see parse_secure_qr) as attributes - straightforward, and handled fully. Cards
    printed more recently carry the newer, binary, digitally-signed "Secure QR" instead; PARSING
    THAT FORMAT IS DELIBERATELY NOT IMPLEMENTED HERE - see parse_secure_qr's own docstring before
    touching it. Milliseconds of CPU, no reason to defer.
  - SLOW (run_ocr_fallback, called only by management/commands/verify_aadhaar_ocr_fallback.py):
    for a card with no QR / an unreadable one, OCR the photo later and hunt the text for exactly
    one Verhoeff-valid 12-digit run, a date of birth, and Aadhaar-specific wording (see
    _looks_like_aadhaar_card - a document that isn't actually an Aadhaar card should never be
    accepted just because it happens to contain a passing 12-digit number). Deferred because OCR
    (a real ML engine or a hosted API call) is a fundamentally different cost than a QR decode,
    and this app's actual load pattern is batches of candidates starting in the same scheduled
    window - this codebase has no task queue (no Celery), so this reuses the exact
    scheduled-command pattern services/video_transcode.py already established for the same reason.

Verification requires BOTH the last-4 digits AND date of birth to match (see _apply_verdict) -
mirrors the joint (aadhaar_last4, date_of_birth) identity key services.duplicate_check already
uses pre-exam. A bare 4-digit suffix match alone is a real coincidence risk (1 in 10,000); pairing
it with a date of birth makes that far less likely to pass by chance.

Storage discipline: a full 12-digit number is held in memory just long enough to validate
(verhoeff_is_valid) and hash (_hash_full_number) - it is NEVER written to any model field, log
line, or exception message anywhere in this module. Only the last 4 digits and a one-way HMAC
hash are ever persisted, matching the exact policy Candidate.aadhaar_last4's own docstring
already states and that test_candidate_identity.py already tests for on that model - see
test_aadhaar.py's TestFullNumberNeverPersisted for the same guarantee extended onto ExamAttempt.
The decoded date of birth is compared in memory only and never persisted either - date_of_birth
already exists on Candidate, so there is nothing new worth storing a second copy of.

This module does NOT touch services/duplicate_check.py. That system runs pre-exam, on
recruiter-typed (aadhaar_last4, date_of_birth), and is a genuine preventive gate - it stays
exactly as it is. find_hash_conflicts below only exists from mid-exam onward (once a photo has
been decoded), so it is structurally a POST-HOC signal for a TA to review, never a gate.
"""

import hashlib
import hmac
import logging
import re
import threading
import xml.etree.ElementTree as ET
from datetime import date

import cv2
import numpy as np
import requests
from django.conf import settings
from django.utils import timezone

from api.models import ExamAttempt

logger = logging.getLogger(__name__)

_AADHAAR_RE = re.compile(r'\d{12}')

# Matches DD-MM-YYYY / DD/MM/YYYY / DD.MM.YYYY - the shapes an Aadhaar card's printed date of
# birth, or a QR's dob attribute, actually uses.
_DOB_RE = re.compile(r'(\d{2})[-/.](\d{2})[-/.](\d{4})')

# A conservative, English-only marker set for "this document is actually an Aadhaar card," not
# some other ID - used only by the OCR fallback path below. The QR path needs no equivalent check:
# a <PrintLetterBarcodeData> XML element (or a UIDAI Secure QR's binary payload) isn't something
# any other document format would ever produce, so the QR's own shape already IS the document-type
# signal. RapidOCR's bundled models are Chinese+English - a Hindi/Devanagari marker ("आधार") would
# never be read reliably, so this stays English-only rather than requiring a script the OCR engine
# can't actually see. Substring, case-insensitive, several close variants rather than one exact
# phrase - OCR noise routinely mangles a word ("Aadhaar" -> "Aadhoar"), and a stricter match would
# reject genuine cards more often than it rejects a different document entirely.
_AADHAAR_CARD_MARKERS = ('aadhaar', 'aadhar', 'uidai', 'unique identification')


def verhoeff_is_valid(digits):
    """True if `digits` (a string of decimal digits) passes the Verhoeff checksum.

    A public, stable algorithm (1969) - unlike UIDAI's own Secure QR format, these tables are not
    something that varies by implementation or changes over time, so this part carries none of
    this module's flagged uncertainty. Catches an OCR misread (a transposed or misrecognised
    digit) before it is ever trusted on the OCR-fallback path.
    """
    if not digits.isdigit():
        return False
    d = [
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
        [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
        [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
        [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
        [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
        [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
        [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
        [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
        [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
    ]
    p = [
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
        [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
        [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
        [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
        [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
        [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
        [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
    ]
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = d[c][p[i % 8][int(ch)]]
    return c == 0


def decode_qr_payload(image_bytes):
    """Raw QR payload text found in `image_bytes`, or None if no QR was detected at all.

    UIDAI-agnostic - this only gets the raw text a QR code encodes; what that payload MEANS (a
    legacy XML string vs. a Secure QR's giant decimal integer) is parse_secure_qr's job below.
    """
    try:
        array = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(array, cv2.IMREAD_COLOR)
        if image is None:
            return None
        payload, _points, _straight = cv2.QRCodeDetector().detectAndDecode(image)
        return payload or None
    except Exception:
        logger.exception('QR decode failed on an identity photo')
        return None


class SecureQrResult:
    """Outcome of parse_secure_qr. `full_number` is intentionally the only place in this module a
    complete Aadhaar number ever lives as a Python value - every caller reads it, uses it
    (verhoeff_is_valid / _hash_full_number), and lets it go out of scope; never assign it to
    anything that outlives one call, log it, or put it in an exception message.

    `dob`/`dob_year`: the cardholder's date of birth as decoded from the QR, if present - a full
    date when the QR's `dob` attribute is available, or just a year (from `yob`) when only that
    is present, which is common on older/partial print-QR formats. At most one of the two is set;
    both are None if neither attribute was present or parseable. Neither attribute name is
    certain across every UIDAI print-QR revision - `yob` (Year Of Birth) is the more consistently
    documented of the two; `dob` is checked too but with lower confidence, same spirit as this
    module's already-flagged uncertainty about the Secure QR format itself.
    """
    def __init__(self, method, full_number, dob=None, dob_year=None):
        self.method = method  # an ExamAttempt.AadhaarVerificationMethod value
        self.full_number = full_number
        self.dob = dob
        self.dob_year = dob_year


def parse_secure_qr(raw_payload):
    """Extract an Aadhaar number (and date of birth, if present) from a QR payload already read
    by decode_qr_payload, or None.

    Two real formats exist on actual Aadhaar cards/e-Aadhaar/mAadhaar downloads:

    - The OLDER, unsigned QR: plain XML text, e.g. a `<PrintLetterBarcodeData uid="..." .../>`
      element with the Aadhaar number as its `uid` attribute, usually alongside a `dob` or `yob`
      attribute. Handled fully below.

    - The NEWER "Secure QR": the payload decodes to one very long decimal integer (not readable
      text) - that integer's raw bytes are gzip-compressed data, which decompresses to a
      delimiter-separated stream of demographic fields followed by a digital signature UIDAI's
      own public key can verify. **Parsing this is deliberately NOT implemented.** The exact byte
      offsets, delimiter value, and field count/order have changed across format revisions, and
      the current UIDAI public-key/certificate distribution mechanism is a live PKI detail this
      module cannot respond to correctly from general knowledge alone - both need to be checked
      against UIDAI's current published specification and validated against real sample cards
      before this branch does anything beyond detecting the format. Shipping a guessed parser
      here risks a WORSE outcome than shipping nothing: a wrong verdict on a real government ID,
      stated with the same confidence as a correct one. A detected Secure QR falls through to
      None here (and from there to the OCR fallback path), exactly like a QR that failed to
      decode at all - never a guessed match or mismatch.
    """
    if raw_payload.isdigit() and len(raw_payload) > 100:
        return None

    try:
        root = ET.fromstring(raw_payload)
    except ET.ParseError:
        return None
    uid = root.attrib.get('uid') or root.attrib.get('UID')
    if not uid or not re.fullmatch(r'\d{12}', uid):
        return None

    dob = None
    dob_attr = root.attrib.get('dob') or root.attrib.get('DOB')
    if dob_attr:
        match = _DOB_RE.fullmatch(dob_attr.strip())
        if match:
            day, month, year = match.groups()
            try:
                dob = date(int(year), int(month), int(day))
            except ValueError:
                dob = None

    dob_year = None
    if dob is None:
        yob_attr = root.attrib.get('yob') or root.attrib.get('YOB')
        if yob_attr and re.fullmatch(r'\d{4}', yob_attr.strip()):
            dob_year = int(yob_attr.strip())

    return SecureQrResult(
        ExamAttempt.AadhaarVerificationMethod.QR_LEGACY, uid, dob=dob, dob_year=dob_year,
    )


def _hash_full_number(full_number):
    """One-way HMAC-SHA256, keyed by settings.AADHAAR_HASH_PEPPER. None if unconfigured - see
    that setting's own comment for why a blank pepper degrades rather than raises.
    """
    if not settings.AADHAAR_HASH_PEPPER:
        return None
    return hmac.new(
        settings.AADHAAR_HASH_PEPPER.encode('utf-8'),
        full_number.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def _apply_verdict(attempt, method, full_number, dob=None, dob_year=None):
    """Shared by the fast (QR) and slow (OCR) paths: given a full number that already passed
    Verhoeff, requires BOTH its last 4 digits AND a date of birth to match the candidate's on-file
    aadhaar_last4/date_of_birth before recording MATCH - see this module's own docstring for why
    last-4-alone isn't trusted any more. `full_number` itself is never assigned to any attribute
    on `attempt`.

    If the candidate's own on-file date_of_birth is blank, or neither `dob` nor `dob_year` could
    be decoded from this source, there simply isn't enough information to compare - no verdict is
    written at all (the attempt stays PENDING, same posture as an unreadable QR), rather than
    recording a false MISMATCH for a data gap that isn't the candidate's fault. Returns True if a
    verdict was actually written, so callers can tell "compared and matched/mismatched" apart from
    "couldn't compare at all" without re-deriving this same condition themselves.
    """
    candidate = attempt.candidate
    if not candidate.date_of_birth or (dob is None and dob_year is None):
        return False

    last4 = full_number[-4:]
    last4_matches = bool(candidate.aadhaar_last4) and last4 == candidate.aadhaar_last4
    dob_matches = (
        dob == candidate.date_of_birth if dob is not None
        else dob_year == candidate.date_of_birth.year
    )

    status = (
        ExamAttempt.AadhaarVerificationStatus.MATCH if last4_matches and dob_matches
        else ExamAttempt.AadhaarVerificationStatus.MISMATCH
    )
    attempt.aadhaar_verification_status = status
    attempt.aadhaar_verification_method = method
    attempt.aadhaar_decoded_last4 = last4
    attempt.aadhaar_number_hash = _hash_full_number(full_number)
    attempt.aadhaar_verified_at = timezone.now()
    attempt.save(update_fields=[
        'aadhaar_verification_status', 'aadhaar_verification_method',
        'aadhaar_decoded_last4', 'aadhaar_number_hash', 'aadhaar_verified_at',
    ])
    return True


def verify_identity_photo(attempt, id_photo_bytes):
    """Fast path only, called synchronously from ExamIdentityCaptureView right after the id_photo
    upload. Tries a QR decode; on success (a Verhoeff-valid number, plus enough date-of-birth
    information to actually compare - see _apply_verdict), writes a terminal verdict. Anything
    else - no QR, an undecodable Secure QR, a checksum failure, no dob/yob attribute to check -
    leaves the attempt PENDING for the candidate's own retry or run_ocr_fallback to pick up later;
    never raises.
    """
    if not settings.AADHAAR_VERIFICATION_ENABLED:
        return
    try:
        payload = decode_qr_payload(id_photo_bytes)
        if not payload:
            return
        result = parse_secure_qr(payload)
        if result is None or not verhoeff_is_valid(result.full_number):
            return
        _apply_verdict(
            attempt, result.method, result.full_number, dob=result.dob, dob_year=result.dob_year,
        )
    except Exception:
        logger.exception('Aadhaar fast-path verification failed for attempt %s', attempt.pk)


_ocr_engine = None
_ocr_engine_lock = threading.Lock()


def _get_ocr_engine():
    """Lazily constructs the RapidOCR engine once per worker process (~0.65s measured) - deferred
    to first real use, not module import time, so a deployment that never turns
    AADHAAR_VERIFICATION_ENABLED on (today's actual default) never pays even the import cost in
    every worker. RapidOCR is free and fully local (no cloud account, no per-call cost) - the
    replacement for an earlier Azure AI Vision integration that was never actually provisioned.
    """
    global _ocr_engine
    if _ocr_engine is None:
        with _ocr_engine_lock:
            if _ocr_engine is None:
                from rapidocr_onnxruntime import RapidOCR
                _ocr_engine = RapidOCR()
    return _ocr_engine


# Bounds concurrent RapidOCR calls PER GUNICORN WORKER PROCESS - see AADHAAR_OCR_MAX_CONCURRENT's
# own comment in settings.py. run_ocr_fallback below runs as a wholly separate OS process (see
# startup.sh's scheduler loop) and needs no guard of its own; this only protects the
# request-handling path try_ocr_inline runs on.
_ocr_semaphore = threading.BoundedSemaphore(settings.AADHAAR_OCR_MAX_CONCURRENT)


def try_ocr_inline(attempt, id_photo_bytes):
    """Synchronous OCR, called from the exam-time Aadhaar capture endpoint only when the fast QR
    path (verify_identity_photo) left the attempt PENDING - this is what makes a real-time verdict
    possible for the many current cards that use the newer Secure QR format this module doesn't
    decode. Never blocks waiting for a slot: if none is free right now, this is skipped outright
    and the attempt simply stays PENDING, a normal outcome the candidate's own retry (or the
    deferred run_ocr_fallback command below) already covers. Returns True if a verdict was applied
    to `attempt`, False otherwise - never raises.
    """
    if not _ocr_semaphore.acquire(blocking=False):
        return False
    try:
        text = _ocr_text(id_photo_bytes)
        number = _extract_verhoeff_valid_number(text)
        if number is None or not _looks_like_aadhaar_card(text):
            return False
        return _apply_verdict(
            attempt, ExamAttempt.AadhaarVerificationMethod.OCR, number, dob=_extract_dob(text),
        )
    except Exception:
        logger.exception('Inline Aadhaar OCR failed for attempt %s', attempt.pk)
        return False
    finally:
        _ocr_semaphore.release()


def run_ocr_fallback(attempt):
    """Slow path, called only by management/commands/verify_aadhaar_ocr_fallback.py - kept as a
    last-resort safety net now that try_ocr_inline exists, for the one case that can't cover:
    its concurrency guard skipped a candidate's own capture-time attempt outright (server was busy
    with a batch start) rather than actually reading their possibly-perfectly-readable photo.
    Downloads the already-uploaded id_photo, OCRs it, and hunts the text for exactly one
    Verhoeff-valid 12-digit run - not "the first 12 digits found", since a candidate's date of
    birth or other printed numbers on the card could otherwise be mistaken for the Aadhaar number.

    Returns 'verified' | 'still_unreadable' | 'skipped' - mirroring
    services.video_transcode.transcode_to_mp4's None-on-failure convention, just as a status
    string since there are two distinct non-success outcomes here worth telling apart in the
    calling command's own summary. Never raises - the command processes many attempts per run.
    """
    if not settings.AADHAAR_VERIFICATION_ENABLED or not attempt.aadhaar_capture_url:
        return 'skipped'
    try:
        from api.services import blob_storage

        read_url = blob_storage.fresh_read_url(attempt.aadhaar_capture_url)
        image_bytes = requests.get(read_url, timeout=15).content

        text = _ocr_text(image_bytes)
        number = _extract_verhoeff_valid_number(text)
        if number is None or not _looks_like_aadhaar_card(text):
            return 'still_unreadable'
        applied = _apply_verdict(
            attempt, ExamAttempt.AadhaarVerificationMethod.OCR, number, dob=_extract_dob(text),
        )
        return 'verified' if applied else 'still_unreadable'
    except Exception:
        logger.exception('Aadhaar OCR fallback failed for attempt %s', attempt.pk)
        return 'still_unreadable'


def _ocr_text(image_bytes):
    """Runs `image_bytes` through RapidOCR and joins every detected text line into one string.
    Shared by both try_ocr_inline and run_ocr_fallback - each already has the relevant bytes in
    hand by the time it calls this, so this function itself does no I/O of its own.
    """
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        return ''
    result, _elapsed = _get_ocr_engine()(image)
    return ' '.join(line[1] for line in result) if result else ''


def _extract_verhoeff_valid_number(text):
    """Exactly one Verhoeff-valid 12-digit run in `text`, or None.

    Deliberately requires exactly one match, not "the first one found" - a candidate's date of
    birth or other printed digits on the same card could otherwise be mistaken for the Aadhaar
    number. Ambiguity (zero or multiple valid candidates) is treated the same as "could not read
    it" rather than guessing.
    """
    candidates = [m for m in _AADHAAR_RE.findall(text.replace(' ', '')) if verhoeff_is_valid(m)]
    return candidates[0] if len(candidates) == 1 else None


def _looks_like_aadhaar_card(text):
    """Whether OCR'd `text` contains at least one Aadhaar-specific marker - see
    _AADHAAR_CARD_MARKERS' own comment for why this is a lenient substring check, and why it's
    English-only. Required alongside a Verhoeff-valid number on the OCR path (see try_ocr_inline/
    run_ocr_fallback) so some other document that happens to carry a passing 12-digit number isn't
    mistaken for an Aadhaar card.
    """
    lowered = text.lower()
    return any(marker in lowered for marker in _AADHAAR_CARD_MARKERS)


def _extract_dob(text):
    """Exactly one unambiguous DD-MM-YYYY-shaped date in `text`, as a date, or None.

    Same "ambiguity means don't guess" posture as _extract_verhoeff_valid_number - a card often
    has more than one date-shaped or digit-group-shaped run on it (an issue date, part of the QR
    code's own text bleeding into the OCR pass), so this requires exactly one candidate that both
    matches the shape AND parses as a real calendar date, never just the first one found.
    """
    candidates = []
    for day, month, year in _DOB_RE.findall(text):
        try:
            candidates.append(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    return candidates[0] if len(candidates) == 1 else None


def find_hash_conflicts(attempt):
    """Other ExamAttempts sharing this attempt's aadhaar_number_hash, for a different candidate.

    Computed live at read time from the indexed hash column - never persisted, never a gate,
    nothing this returns automatically flags or blocks anyone. This is a POST-HOC signal only:
    the pre-exam services.duplicate_check gate (last4+DOB, recruiter-entered) runs before any
    photo exists and is completely independent of this - see that module for the real gate.
    Empty when there is no hash yet (PENDING/unreadable) or no conflict found.
    """
    if not attempt.aadhaar_number_hash:
        return []
    others = (
        ExamAttempt.objects
        .filter(aadhaar_number_hash=attempt.aadhaar_number_hash)
        .exclude(pk=attempt.pk)
        .exclude(candidate=attempt.candidate)
        .select_related('candidate', 'candidate__batch')
    )
    return [
        {
            'candidate_id': other.candidate.candidate_id,
            'candidate_name': other.candidate.full_name,
            'batch_name': other.candidate.batch.batch_name,
            'attempt_id': other.attempt_id,
        }
        for other in others
    ]


def can_retry(attempt):
    """Whether the exam-time Aadhaar capture endpoint should still accept another (re)capture
    from this candidate. Unlimited by policy: the exam cannot begin without a confirmed match (see
    views.exam.ExamIdentityCaptureView), so the only way forward for an unmatched candidate is to
    keep retrying, never to be waved through after some cap. False only once matched, since
    there's nothing left to fix at that point - a resubmit then just re-returns the frozen verdict
    rather than re-running verification for no reason.
    """
    return attempt.aadhaar_verification_status != ExamAttempt.AadhaarVerificationStatus.MATCH


def capture_response(attempt):
    """The verdict payload returned by the exam-time Aadhaar capture endpoint on every call (fresh
    capture or retry alike).
    """
    return {
        'aadhaar_verification_status': attempt.aadhaar_verification_status,
        'aadhaar_verification_status_display': attempt.get_aadhaar_verification_status_display(),
        'aadhaar_verification_method': attempt.aadhaar_verification_method,
        'aadhaar_decoded_last4': attempt.aadhaar_decoded_last4,
        'aadhaar_attempts_used': attempt.aadhaar_verification_attempts,
        'aadhaar_can_retry': can_retry(attempt),
        'aadhaar_verification_enabled': settings.AADHAAR_VERIFICATION_ENABLED,
    }
