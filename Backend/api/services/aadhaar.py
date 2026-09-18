"""Automated Aadhaar identity verification for the exam-time identity-capture flow.

Gated end-to-end by settings.AADHAAR_VERIFICATION_ENABLED, which defaults to ON in every
environment - the flag exists as an emergency kill switch, not as a normal opt-in, so in practice
this module is always live. Turning it off is the exception. While it IS on, this deliberately gates exam
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
    accepted just because it happens to contain a passing 12-digit number). Failing that, for a
    MASKED card ("XXXX XXXX 5991") the last four digits alone - the default output of both UIDAI's
    e-Aadhaar download and DigiLocker, where no full number is printed to checksum at all; see
    _apply_masked_verdict for exactly what that costs. Deferred because OCR
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

# Three groups of 4 digits, an OPTIONAL single space between each, and - critically - NOT
# immediately preceded or followed by another digit. Matches an Aadhaar number exactly as UIDAI
# prints it (grouped "6343 5121 2737") AND as OCR often reads it with the spaces collapsed
# ("634351212737"), while the (?<!\d)/(?!\d) boundary checks stop it from EVER reading into a
# digit run that belongs to something else - which is exactly what broke on real captures with
# two different, real, non-hypothetical shapes:
#   1. A prior version stripped every space before scanning with a plain r'\d{12}', so an OCR'd
#      DOB year sitting directly before the number with only a real, natural space between them
#      ('...03/03/2004 680499533624') had that space thrown away FIRST - turning two separate,
#      cleanly-delimited numbers into one 16-digit run, then only checking for a 12-digit window
#      starting at its first digit (part year, part number, not the real number at all).
#   2. A version that scanned every possible window inside a digit run (to fix the above without
#      restoring the space) then found SPURIOUS matches straddling the boundary between two
#      adjacent, genuine printings of the SAME real number - a real card prints its own number
#      more than once, often separated only by a single space - and some of those boundary-
#      spanning fragments happened to also pass the Verhoeff checksum, which the "must be exactly
#      one DISTINCT valid candidate" rule then read as unresolvable ambiguity.
# Anchoring on real digit boundaries instead of blindly collapsing whitespace fixes both: it
# finds the number whether OCR grouped it with spaces or not, without ever needing to guess
# which spaces were "part of the number" and which weren't.
_AADHAAR_RE = re.compile(r'(?<!\d)(\d{4})\s?(\d{4})\s?(\d{4})(?!\d)')

# A MASKED Aadhaar number - "XXXX XXXX 5991" - where only the last four digits are printed at all.
#
# Not an edge case: this is what UIDAI's own e-Aadhaar download and DigiLocker now produce by
# DEFAULT, so it is the normal card for any candidate who photographs a downloaded PDF or a phone
# screen instead of a physical card. Confirmed against real captures this system rejected. There
# is no full number here to checksum - see _apply_masked_verdict for what that costs and why it is
# still worth accepting.
#
# The mask is written with X on both UIDAI's and DigiLocker's output; '*' is allowed too because
# some third-party renderers use it, and lowercase because OCR routinely reads a boxy uppercase X
# as one. The leading lookbehind keeps this from firing inside a word (a stray "MAXXXX..." in
# noisy OCR text), and \s* rather than \s lets it survive OCR collapsing or inserting the spacing
# between the mask groups.
_MASKED_AADHAAR_RE = re.compile(r'(?<![0-9A-Za-z])[Xx*]{4}\s*[Xx*]{4}\s*(\d{4})(?!\d)')

# A Virtual ID, printed directly under the Aadhaar number on a real physical card
# ("VID : 9194 3855 4334 4604"). Removed from the text BEFORE hunting for the Aadhaar number,
# because _AADHAAR_RE's digit-boundary anchoring does not exclude it: the VID's first three
# groups are a 12-digit run whose next character is a space, so it is offered as a candidate like
# any other. It then only has to pass Verhoeff by chance - roughly one card in ten - to become a
# second DISTINCT valid candidate, which _extract_verhoeff_valid_number reads as unresolvable
# ambiguity and rejects the whole card for. Stripping it beforehand is what keeps that from ever
# being a contest.
#
# Stripped rather than excluded by a lookaround: the obvious lookaround ("not followed by another
# space-separated group of four") would also reject the same number printed twice in a row, which
# real cards do and which _extract_verhoeff_valid_number's dedupe exists specifically to handle.
# V[I1L] because OCR reads that glyph as a one or an L about as often as an I.
_VID_RE = re.compile(r'V[I1L]D\s*:?\s*(?:\d{4}\s*){3}\d{4}', re.IGNORECASE)

# Matches DD-MM-YYYY / DD/MM/YYYY / DD.MM.YYYY - the shapes an Aadhaar card's printed date of
# birth, or a QR's dob attribute, actually uses.
_DOB_RE = re.compile(r'(\d{2})[-/.](\d{2})[-/.](\d{4})')

# A date immediately labelled "DOB" (UIDAI's own standard print label, "DOB : DD/MM/YYYY" or
# "DOB:DD/MM/YYYY" with no space once OCR collapses it) - see _extract_dob's own docstring for why
# this has to be tried before the older "exactly one date-shaped run in the whole text" rule.
# D[O0]B, not a literal "DOB": confirmed against real production OCR text reading the label as
# "D0B" (the digit 0, not the letter O) - a common OCR confusion for that exact glyph pair, and
# without this the labelled match silently fails to fire and falls back to the ambiguous
# multi-date rule below, which then found the card's own "issued" date alongside the real DOB
# and returned None for both - the same failure mode this label-first rule exists to prevent.
_LABELLED_DOB_RE = re.compile(r'D[O0]B\s*:?\s*(\d{2})[-/.](\d{2})[-/.](\d{4})', re.IGNORECASE)

# The same label, but YYYY/MM/DD - what a DigiLocker-issued Aadhaar prints ("DOB: 2000/07/01"),
# confirmed against a real capture. Kept as its own pattern rather than widened into the one
# above because the two cannot be confused: a 4-2-2 date can never match the 2-2-4 pattern and
# vice versa, so trying them in turn is unambiguous, whereas a single pattern accepting either
# would have to guess which end held the year for a date like 01/02/2003.
_LABELLED_DOB_YMD_RE = re.compile(
    r'D[O0]B\s*:?\s*(\d{4})[-/.](\d{2})[-/.](\d{2})', re.IGNORECASE,
)

# A conservative, English-only marker set for "this document is actually an Aadhaar card," not
# some other ID - used only by the OCR fallback path below. The QR path needs no equivalent check:
# a <PrintLetterBarcodeData> XML element (or a UIDAI Secure QR's binary payload) isn't something
# any other document format would ever produce, so the QR's own shape already IS the document-type
# signal. RapidOCR's bundled models are Chinese+English - a Hindi/Devanagari marker ("आधार") would
# never be read reliably, so this stays English-only rather than requiring a script the OCR engine
# can't actually see. Substring, case-insensitive, several close variants rather than one exact
# phrase - OCR noise routinely mangles a word ("Aadhaar" -> "Aadhoar"), and a stricter match would
# reject genuine cards more often than it rejects a different document entirely.
#
# 'government of india' added after a real, otherwise-perfectly-read capture (name, DOB, gender,
# a Verhoeff-valid number all correct) was rejected here: the card's own "Aadhaar"/"UIDAI" header
# text simply wasn't in frame - unsurprising, since the candidate-facing instructions ask for a
# close, legible shot of the number and DOB specifically, not the whole card. "Government of
# India" is printed directly on the bio-data section itself (not just the header), so it survives
# exactly the tight crop those instructions encourage. Its own genericness is a smaller risk than
# it looks: this check is a coarse pre-filter, not the real safeguard against a false match - that
# is the Verhoeff checksum (already a strong filter on its own) AND the subsequent requirement
# that the extracted last4+DOB match THIS SPECIFIC candidate's own stored records.
_AADHAAR_CARD_MARKERS = ('aadhaar', 'aadhar', 'uidai', 'unique identification', 'government of india')


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


def _record_verdict(attempt, method, last4, number_hash, dob, dob_year):
    """The comparison and the write, shared by every path that can produce a verdict.

    Requires BOTH the last 4 digits AND a date of birth to match the candidate's on-file
    aadhaar_last4/date_of_birth before recording MATCH - see this module's own docstring for why
    last-4-alone isn't trusted. No full number is ever passed in or assigned to `attempt`; the
    callers reduce it to these two values first.

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
    attempt.aadhaar_number_hash = number_hash
    attempt.aadhaar_verified_at = timezone.now()
    attempt.save(update_fields=[
        'aadhaar_verification_status', 'aadhaar_verification_method',
        'aadhaar_decoded_last4', 'aadhaar_number_hash', 'aadhaar_verified_at',
    ])
    return True


def _apply_verdict(attempt, method, full_number, dob=None, dob_year=None):
    """Verdict from a FULL 12-digit number that already passed Verhoeff - the QR paths and the
    OCR path for an unmasked card. `full_number` is reduced to its last 4 and its one-way hash
    here and never assigned to any attribute on `attempt`.
    """
    return _record_verdict(
        attempt, method, full_number[-4:], _hash_full_number(full_number), dob, dob_year,
    )


def _apply_masked_verdict(attempt, last4, dob):
    """Verdict from a MASKED card ("XXXX XXXX 5991"), where no full number exists to read.

    Two things are unavoidably weaker here, both worth stating plainly:

      - No Verhoeff checksum. On the full-number path the checksum is a strong filter against
        some unrelated 12-digit run being mistaken for an Aadhaar number; four digits behind a
        mask carry no such self-check. What remains is still substantial: the text must carry an
        Aadhaar-specific marker (_looks_like_aadhaar_card), the mask pattern itself is a shape no
        ordinary document produces, and the last 4 must match THIS candidate's on-file value.
      - No aadhaar_number_hash, so find_hash_conflicts cannot see a masked capture at all. That
        signal is post-hoc and advisory, never a gate, so its absence narrows what a TA is shown
        rather than letting anything through - but a TA reading a conflict list should know it
        only covers unmasked captures. This is why the method is recorded distinctly rather than
        as plain OCR.

    Requires a full `dob`, never a bare year: a masked card always prints the complete date, so
    accepting a year-only match here would weaken the pairing for no practical gain. Passing
    dob=None leaves the attempt PENDING via _record_verdict's own guard.

    The alternative was to keep rejecting these, which is what the system did until now - and
    since a masked download is UIDAI's and DigiLocker's DEFAULT output, that rejected candidates
    holding a perfectly genuine card and left them unable to start at all.
    """
    return _record_verdict(
        attempt, ExamAttempt.AadhaarVerificationMethod.OCR_MASKED, last4, None, dob, None,
    )


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
        return verdict_from_ocr_text(attempt, _ocr_text(id_photo_bytes))
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

        applied = verdict_from_ocr_text(attempt, _ocr_text(image_bytes))
        return 'verified' if applied else 'still_unreadable'
    except Exception:
        logger.exception('Aadhaar OCR fallback failed for attempt %s', attempt.pk)
        return 'still_unreadable'



# RapidOCR's own default (Det.limit_type: min in its config.yaml) only enforces a FLOOR on the
# shorter side - it never downscales a large image, so the detector runs at the photo's native
# resolution. Measured directly against this project's installed RapidOCR: a 4000x3000 image (a
# realistic scanned upload, now that PhotoCapture offers one) took 13.6s; capped to 1600px on the
# longer side first, the same image took 1.8s - over 7x faster, with no accuracy cost since
# Aadhaar card text is easily legible well below this resolution. This is what keeps a real
# capture inside the "a few seconds" budget users actually expect, instead of scaling with
# whatever resolution a candidate's scanner or phone happened to produce.
_OCR_MAX_IMAGE_SIDE = 1600


def _ocr_text(image_bytes):
    """Runs `image_bytes` through RapidOCR and joins every detected text line into one string.
    Shared by both try_ocr_inline and run_ocr_fallback - each already has the relevant bytes in
    hand by the time it calls this, so this function itself does no I/O of its own.
    """
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        return ''
    height, width = image.shape[:2]
    longer_side = max(height, width)
    if longer_side > _OCR_MAX_IMAGE_SIDE:
        scale = _OCR_MAX_IMAGE_SIDE / longer_side
        image = cv2.resize(image, (round(width * scale), round(height * scale)),
                           interpolation=cv2.INTER_AREA)
    result, _elapsed = _get_ocr_engine()(image)
    return ' '.join(line[1] for line in result) if result else ''


def _extract_verhoeff_valid_number(text):
    """Exactly one DISTINCT Verhoeff-valid 12-digit run in `text`, or None.

    Deliberately requires exactly one distinct candidate, not "the first one found" - a
    candidate's date of birth or other printed digits on the same card could otherwise be
    mistaken for the Aadhaar number. Ambiguity (zero or multiple DIFFERING valid candidates) is
    treated the same as "could not read it" rather than guessing.

    Deduplicated (a set, not a list) because a real card prints its own number more than once -
    confirmed against real production OCR text, where a clear, detailed capture read the same
    valid number three times (once near the photo, once under "Your Aadhaar No.", once near the
    VID). Three copies of the SAME number is not an ambiguity to bail out on - it's the opposite,
    stronger evidence - but a version of this function that didn't dedupe treated it exactly
    like three DIFFERENT numbers, and rejected every one of them. _AADHAAR_RE's own digit-
    boundary anchoring (see its comment) is what keeps those three genuine repeats from ever
    being read as a fourth, spurious, boundary-straddling "candidate" in the first place.

    Not run against text.replace(' ', '') - _AADHAAR_RE handles the number's own optional
    internal spacing itself. Blindly stripping every space in the whole text was the earlier
    bug: it could turn two separate, legitimately space-delimited numbers (a preceding date and
    the real number, or two genuine printings of the same number) into one indistinguishable
    digit run.
    """
    searchable = _VID_RE.sub(' ', text)
    candidates = {''.join(m) for m in _AADHAAR_RE.findall(searchable)}
    valid_candidates = {c for c in candidates if verhoeff_is_valid(c)}
    return next(iter(valid_candidates)) if len(valid_candidates) == 1 else None


def _extract_masked_last4(text):
    """The last 4 digits off exactly one DISTINCT masked Aadhaar number in `text`, or None.

    Same "exactly one distinct candidate, else it's ambiguous" discipline as the full-number
    function above, and for the same reason: two different masked suffixes in one image means
    two cards are in frame, and guessing which one belongs to the candidate is not something
    this should do. Two printings of the SAME suffix dedupe to one and are accepted, again
    matching the full-number path - an e-Aadhaar prints its masked number more than once.
    """
    candidates = set(_MASKED_AADHAAR_RE.findall(text))
    return next(iter(candidates)) if len(candidates) == 1 else None


def verdict_from_ocr_text(attempt, text):
    """Turn OCR'd card text into a verdict, or return False if it cannot be read.

    Shared by try_ocr_inline and run_ocr_fallback so the two cannot drift - they had already
    grown identical copies of this sequence, and the masked path would have had to be added to
    both.

    Order matters: a full, checksum-verified number is strictly stronger evidence than a masked
    suffix and also produces the cross-attempt hash, so it is always preferred when the card
    shows one. The masked read is the fallback for a card that never printed one.
    """
    if not _looks_like_aadhaar_card(text):
        return False

    full_number = _extract_verhoeff_valid_number(text)
    if full_number is not None:
        return _apply_verdict(
            attempt, ExamAttempt.AadhaarVerificationMethod.OCR, full_number,
            dob=_extract_dob(text),
        )

    masked_last4 = _extract_masked_last4(text)
    if masked_last4 is not None:
        return _apply_masked_verdict(attempt, masked_last4, _extract_dob(text))

    return False


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
    """The cardholder's date of birth from OCR'd `text`, as a date, or None.

    Tries a date explicitly labelled "DOB" first (UIDAI's own standard print label on every real
    Aadhaar card) - confirmed necessary, not a defensive guess: every genuine Aadhaar card ALSO
    prints a separate "Aadhaar no. issued: DD/MM/YYYY" date in the exact same DD/MM/YYYY shape, so
    an earlier version of this function (requiring exactly one date-shaped run in the whole text)
    found two equally-plausible candidates on every single real card tested and returned None
    every time - confirmed against real production OCR text ('...issued:01/04/2012...
    DOB:13/10/2003...'), not a hypothetical. Falls back to the old "exactly one, else ambiguous"
    rule only if no labelled DOB is found, in case OCR mangled the word "DOB" itself but still
    read the digits cleanly.
    """
    labelled = _LABELLED_DOB_RE.search(text)
    if labelled:
        day, month, year = labelled.groups()
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            pass  # fall through - the label matched but the digits don't form a real date

    # Same label, the other way round - a DigiLocker Aadhaar prints "DOB: 2000/07/01".
    labelled_ymd = _LABELLED_DOB_YMD_RE.search(text)
    if labelled_ymd:
        year, month, day = labelled_ymd.groups()
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            pass

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
