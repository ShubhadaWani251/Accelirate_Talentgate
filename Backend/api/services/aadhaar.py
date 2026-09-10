"""Automated Aadhaar identity verification for the exam-time identity-capture flow.

Gated end-to-end by settings.AADHAAR_VERIFICATION_ENABLED (default off) - nothing in this module
does anything until that flag is explicitly turned on, and even then nothing here can ever be the
reason a genuine candidate's exam fails to start or starts late; every public function below
degrades to "leave the verdict as PENDING/unreadable" on any failure rather than raising into the
identity-capture request. Same guarantee api/services/seb.py already gives for SEB verification.

Two paths, matching how differently they cost:
  - FAST (verify_identity_photo): decode the QR on the captured id_photo. A legacy (pre-Secure-QR)
    Aadhaar card's QR is a plain, unsigned XML payload with the Aadhaar number as an attribute -
    straightforward, and handled fully. Cards printed more recently carry the newer, binary,
    digitally-signed "Secure QR" instead; PARSING THAT FORMAT IS DELIBERATELY NOT IMPLEMENTED
    HERE - see parse_secure_qr's own docstring before touching it. Milliseconds of CPU, no reason
    to defer.
  - SLOW (run_ocr_fallback, called only by management/commands/verify_aadhaar_ocr_fallback.py):
    for a card with no QR / an unreadable one, OCR the photo later and hunt the text for exactly
    one Verhoeff-valid 12-digit run. Deferred because OCR (a real ML engine or a hosted API call)
    is a fundamentally different cost than a QR decode, and this app's actual load pattern is
    batches of candidates starting in the same scheduled window - this codebase has no task
    queue (no Celery), so this reuses the exact scheduled-command pattern
    services/video_transcode.py already established for the same reason.

Storage discipline: a full 12-digit number is held in memory just long enough to validate
(verhoeff_is_valid) and hash (_hash_full_number) - it is NEVER written to any model field, log
line, or exception message anywhere in this module. Only the last 4 digits and a one-way HMAC
hash are ever persisted, matching the exact policy Candidate.aadhaar_last4's own docstring
already states and that test_candidate_identity.py already tests for on that model - see
test_aadhaar.py's TestFullNumberNeverPersisted for the same guarantee extended onto ExamAttempt.

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

import cv2
import numpy as np
import requests
from django.conf import settings
from django.utils import timezone

from api.models import ExamAttempt

logger = logging.getLogger(__name__)

_AADHAAR_RE = re.compile(r'\d{12}')

# How many times a candidate may (re)capture the Aadhaar photo through the exam-time capture
# endpoint before that flow stops offering a retry and lets them continue regardless, flagged for
# a TA (see can_retry/needs_manual_review below) - never a hard block, per this module's own
# guarantee. Deliberately small: a candidate-driven retake costs THEM real time in front of a
# webcam before their exam has even started. One careful retake fixes a blurry photo or bad
# glare; a photo that still fails on a second try is a genuine mismatch or an unreadable card,
# which a third attempt does not fix - it only delays exam start for no better odds. Reuses the
# existing aadhaar_verification_attempts field - no new model field, no migration.
AADHAAR_CAPTURE_MAX_ATTEMPTS = 2


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
    """
    def __init__(self, method, full_number):
        self.method = method  # an ExamAttempt.AadhaarVerificationMethod value
        self.full_number = full_number


def parse_secure_qr(raw_payload):
    """Extract an Aadhaar number from a QR payload already read by decode_qr_payload, or None.

    Two real formats exist on actual Aadhaar cards/e-Aadhaar/mAadhaar downloads:

    - The OLDER, unsigned QR: plain XML text, e.g. a `<PrintLetterBarcodeData uid="..." .../>`
      element with the Aadhaar number as its `uid` attribute. Handled fully below.

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
    return SecureQrResult(ExamAttempt.AadhaarVerificationMethod.QR_LEGACY, uid)


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


def _apply_verdict(attempt, method, full_number):
    """Shared by the fast (QR) and slow (OCR) paths: given a full number that already passed
    Verhoeff, compare its last 4 against the candidate's on-file aadhaar_last4 and save the
    verdict. `full_number` itself is never assigned to any attribute on `attempt`.
    """
    last4 = full_number[-4:]
    on_file = attempt.candidate.aadhaar_last4
    status = (
        ExamAttempt.AadhaarVerificationStatus.MATCH if on_file and last4 == on_file
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


def verify_identity_photo(attempt, id_photo_bytes):
    """Fast path only, called synchronously from ExamIdentityCaptureView right after the id_photo
    upload. Tries a QR decode; on success (and a Verhoeff-valid number), writes a terminal
    verdict. Anything else - no QR, an undecodable Secure QR, a checksum failure - leaves the
    attempt PENDING for run_ocr_fallback to pick up later; never raises, never blocks exam start.
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
        _apply_verdict(attempt, result.method, result.full_number)
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
        number = _extract_verhoeff_valid_number(_ocr_text(id_photo_bytes))
        if number is None:
            return False
        _apply_verdict(attempt, ExamAttempt.AadhaarVerificationMethod.OCR, number)
        return True
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

        number = _extract_verhoeff_valid_number(_ocr_text(image_bytes))
        if number is None:
            return 'still_unreadable'
        _apply_verdict(attempt, ExamAttempt.AadhaarVerificationMethod.OCR, number)
        return 'verified'
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
    from this candidate. False once matched (nothing left to fix) or once
    AADHAAR_CAPTURE_MAX_ATTEMPTS has been used - at which point the endpoint returns the frozen
    verdict instead of re-verifying, and the candidate proceeds regardless (see
    needs_manual_review) rather than being blocked.
    """
    return (
        attempt.aadhaar_verification_status != ExamAttempt.AadhaarVerificationStatus.MATCH
        and attempt.aadhaar_verification_attempts < AADHAAR_CAPTURE_MAX_ATTEMPTS
    )


def needs_manual_review(attempt):
    """Whether this attempt's Aadhaar verification is a settled non-match a TA should look at.

    Deliberately derived from already-persisted fields, not a stored flag: if the deferred
    run_ocr_fallback command later succeeds on a photo the candidate's own attempts couldn't
    resolve, aadhaar_verification_status flips to MATCH and this clears itself automatically -
    nothing to remember to unset.
    """
    return (
        attempt.aadhaar_verification_status != ExamAttempt.AadhaarVerificationStatus.MATCH
        and attempt.aadhaar_verification_attempts >= AADHAAR_CAPTURE_MAX_ATTEMPTS
    )


def capture_response(attempt):
    """The verdict payload returned by the exam-time Aadhaar capture endpoint on every call (fresh
    capture or retry alike) - also the single source of truth can_retry/needs_manual_review-shaped
    data should be read from, so the API response and any TA-facing serializer never drift apart.
    """
    return {
        'aadhaar_verification_status': attempt.aadhaar_verification_status,
        'aadhaar_verification_status_display': attempt.get_aadhaar_verification_status_display(),
        'aadhaar_verification_method': attempt.aadhaar_verification_method,
        'aadhaar_decoded_last4': attempt.aadhaar_decoded_last4,
        'aadhaar_attempts_used': attempt.aadhaar_verification_attempts,
        'aadhaar_attempts_allowed': AADHAAR_CAPTURE_MAX_ATTEMPTS,
        'aadhaar_can_retry': can_retry(attempt),
        'aadhaar_needs_manual_review': needs_manual_review(attempt),
        'aadhaar_verification_enabled': settings.AADHAAR_VERIFICATION_ENABLED,
    }
