"""Validation for candidate rows on the Upload Review screen.

One row can be wrong in several ways at once - a missing name AND a malformed email AND an
address that already appears three rows above. The screen has to show all of them, because
fixing one and re-uploading only to be told about the next is exactly the loop this step
exists to avoid.

Everything here works on plain values rather than on a request, so the identical checks run
for a freshly-parsed spreadsheet and for a row corrected in place afterwards. A row can
therefore never be edited into a state the original upload would have rejected.
"""

import re
from collections import Counter

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email as django_validate_email

from api.models import Candidate

# field name on Candidate -> the column label the reviewer sees. The label is what gets
# reported in `error_fields`, so the UI can tint the offending cell without a second mapping,
# and it's the same wording used in the spreadsheet template.
EDITABLE_FIELDS = {
    # 'Name' rather than 'First Name': the spreadsheet has one Name column, which is split on
    # the first space, and the reviewer thinks in terms of that column. The label doubles as
    # the error_fields key the UI highlights cells by, so it has to match the column heading.
    'first_name': 'Name',
    'last_name': 'Last Name',
    'email': 'Email',
    'phone': 'Mobile',
    'aadhaar_last4': 'Aadhaar Last 4 Digits',
    'college_name': 'College Name',
    'degree': 'Degree',
    'stream': 'Stream',
    'percentage': 'Percentage',
    'passing_out_year': 'Passing Out Year',
    'location': 'Location',
}

_AADHAAR_RE = re.compile(r'^\d{4}$')
_MOBILE_STRIP_RE = re.compile(r'[\s\-().]')
_MOBILE_RE = re.compile(r'^\+?\d{10,15}$')
# A text field that is nothing but digits/punctuation is a mis-shifted column, not a real name
# or college - "12345" as a name means the spreadsheet's columns don't line up.
_HAS_LETTER_RE = re.compile(r'[^\W\d_]', re.UNICODE)
_NUMERIC_RE = re.compile(r'^\d+(\.\d+)?$')

# Nothing outside this range is a plausible graduation year, and a typo'd 202 or 20255 is
# worth catching before it reaches a report.
_MIN_YEAR, _MAX_YEAR = 1950, 2100

_VS = Candidate.ValidationStatus

# Free-text fields that must contain at least one letter when filled in. Keyed by field name,
# valued by the column label shown to the reviewer. Presence itself is checked separately
# (each field below has its own required check) - this only catches a filled-in value that's
# nothing but digits, meaning the spreadsheet's columns are mis-aligned.
_TEXT_FIELDS = (
    ('first_name', 'Name'),
    ('college_name', 'College Name'),
    ('degree', 'Degree'),
    ('stream', 'Stream'),
    ('location', 'Location'),
)

# Required text fields with no other format rule - just "must not be blank". Degree/Stream/
# Location are checked here; Name and College have their own checks above because they came
# first historically, but the effect is identical.
_REQUIRED_TEXT_FIELDS = (
    ('degree', 'Degree', _VS.MISSING_DEGREE),
    ('stream', 'Stream', _VS.MISSING_STREAM),
    ('location', 'Location', _VS.MISSING_LOCATION),
)


def normalize_email(value):
    return (value or '').strip().lower()


def normalize_name(value):
    """Casefold and collapse whitespace, so "Asha  Rao" and "asha rao" are one person."""
    return ' '.join((value or '').split()).casefold()


def identity_key(values):
    """The composite key that identifies a candidate across uploads and batches.

    Only the last 4 Aadhaar digits are stored, and 4 digits is far too weak to identify anyone
    on its own - there are 10,000 possible values, so in a 50-row batch there is roughly a 1-in-8
    chance two unrelated candidates share a suffix. Pairing the digits with the name makes a
    collision require both, which is rare enough to treat as the same person.

    The trade-off is the opposite failure: the same person entered under a differently spelled
    name (or a maiden name) reads as two people. That is the safer direction - a missed duplicate
    is reviewed by a human, whereas a false duplicate can block a legitimate candidate from
    being invited at all.

    `values` is the dict shape returned by _values_of / used by validate_candidate_values.
    """
    last4 = (values.get('aadhaar_last4') or '').strip()
    name = normalize_name(
        f"{values.get('first_name') or ''} {values.get('last_name') or ''}"
    )
    return (last4, name)


def candidate_identity_key(candidate):
    """identity_key for a saved Candidate row."""
    return identity_key({
        'aadhaar_last4': candidate.aadhaar_last4,
        'first_name': candidate.first_name,
        'last_name': candidate.last_name,
    })


def is_valid_email(value):
    try:
        django_validate_email((value or '').strip())
    except DjangoValidationError:
        return False
    return True


def is_valid_mobile(value):
    return bool(_MOBILE_RE.match(_MOBILE_STRIP_RE.sub('', (value or '').strip())))


def validate_candidate_values(values, email_counts=None, raw=None, aadhaar_counts=None):
    """Check one row, column by column. Returns (validation_status, errors).

    `errors` is every problem found, in the order they're reported on screen:
    [{'field': 'Email', 'message': 'Invalid email format'}, ...]. Messages are deliberately
    terse - they sit in a narrow table cell next to nine other columns, so "Must be 12 digits"
    reads better there than a full sentence naming the offending value, which the row already
    shows. The returned status is the FIRST error's category (or OK) - it drives the status
    pill and the finalize gate, while the list drives the Errors column.

    `email_counts` / `aadhaar_counts` are Counters across the whole batch; a row whose address
    or Aadhaar appears more than once is flagged. Both are scoped to the batch on purpose: the
    same person legitimately reappears in a later batch (that's the cooling-off check), but
    twice in one upload is a mistake in the sheet.

    `raw` is Candidate.upload_raw - the original spreadsheet text for fields whose model type
    can't hold a bad value. Without it a Percentage cell reading "abc" is stored as NULL and
    is indistinguishable from an empty one, so "must be a number" could never be reported.
    """
    errors = []
    statuses = []
    raw = raw or {}

    def fail(status, field, message):
        statuses.append(status)
        errors.append({'field': field, 'message': message})

    # --- Name (required) -------------------------------------------------------------
    first_name = (values.get('first_name') or '').strip()
    if not first_name:
        fail(_VS.MISSING_NAME, 'Name', 'Name required')

    # --- Email (required, format, unique within the batch) ---------------------------
    email = (values.get('email') or '').strip()
    if not email:
        fail(_VS.MISSING_EMAIL, 'Email', 'Email required')
    elif not is_valid_email(email):
        fail(_VS.INVALID_EMAIL, 'Email', 'Invalid email format')
    elif email_counts and email_counts.get(normalize_email(email), 0) > 1:
        fail(_VS.DUPLICATE_EMAIL, 'Email', 'Duplicate email in this batch')

    # --- Aadhaar (required, exactly 12 digits, unique within the batch) --------------
    # Only the last 4 digits are held (see models/candidate.py), so on their own they are a
    # weak identifier - 10,000 possible values means unrelated people collide routinely. The
    # within-batch duplicate check is therefore on (last 4 + name), not the digits alone;
    # flagging every shared suffix would bury the reviewer in false duplicates. The
    # cross-batch cooling-off check keys on the same pair - see services/duplicate_check.py.
    aadhaar = (values.get('aadhaar_last4') or '').strip()
    if not aadhaar:
        fail(_VS.MISSING_AADHAAR, 'Aadhaar Last 4 Digits', 'Aadhaar last 4 digits required')
    elif not _AADHAAR_RE.match(aadhaar):
        fail(_VS.INVALID_AADHAAR, 'Aadhaar Last 4 Digits', 'Must be exactly 4 digits')
    elif aadhaar_counts and aadhaar_counts.get(identity_key(values), 0) > 1:
        fail(_VS.DUPLICATE_AADHAAR, 'Aadhaar Last 4 Digits',
             'Same name and Aadhaar last 4 digits already appear in this batch')

    # --- College (required) ----------------------------------------------------------
    if not (values.get('college_name') or '').strip():
        fail(_VS.MISSING_COLLEGE, 'College Name', 'College required')

    # --- Degree / Stream / Location (required, free text) ----------------------------
    for field, label, missing_status in _REQUIRED_TEXT_FIELDS:
        if not (values.get(field) or '').strip():
            fail(missing_status, label, f'{label} required')

    # --- Text fields must not be all digits -----------------------------------------
    # A name or college of "12345" means the spreadsheet's columns are mis-aligned, which is
    # worth catching loudly - it usually affects every row in the file. Only runs against a
    # value that's actually present - blank already failed its own required check above.
    for field, label in _TEXT_FIELDS:
        text = (values.get(field) or '').strip()
        if text and not _HAS_LETTER_RE.search(text):
            fail(_VS.INVALID_TEXT, label, f'{label} cannot be only numbers')

    # --- Percentage (required; numeric 0-100) -----------------------------------------
    raw_percentage = (raw.get('percentage') or '').strip()
    percentage = values.get('percentage')
    if not raw_percentage and percentage is None:
        fail(_VS.MISSING_PERCENTAGE, 'Percentage', 'Percentage required')
    elif raw_percentage and percentage is None:
        fail(_VS.INVALID_PERCENTAGE, 'Percentage', 'Must be a number')
    elif percentage is not None and not (0 <= float(percentage) <= 100):
        fail(_VS.INVALID_PERCENTAGE, 'Percentage', 'Must be between 0 and 100')

    # --- Passing Out Year (required; 4 digits in a plausible range) ------------------
    raw_year = (raw.get('passing_out_year') or '').strip()
    year = values.get('passing_out_year')
    if not raw_year and year is None:
        fail(_VS.MISSING_YEAR, 'Passing Out Year', 'Passing Out Year required')
    elif raw_year and year is None:
        fail(_VS.INVALID_YEAR, 'Passing Out Year', 'Must be a 4-digit year')
    elif year is not None and not (_MIN_YEAR <= int(year) <= _MAX_YEAR):
        fail(_VS.INVALID_YEAR, 'Passing Out Year',
             f'Must be between {_MIN_YEAR} and {_MAX_YEAR}')

    # --- Mobile (required; 10-15 digits) ----------------------------------------------
    mobile = (values.get('phone') or '').strip()
    if not mobile:
        fail(_VS.MISSING_MOBILE, 'Mobile', 'Mobile required')
    elif not is_valid_mobile(mobile):
        fail(_VS.INVALID_MOBILE, 'Mobile', 'Must be 10-15 digits')

    return (statuses[0] if statuses else _VS.OK), errors


def _values_of(candidate):
    return {field: getattr(candidate, field) for field in EDITABLE_FIELDS}


def revalidate_batch_candidates(batch, candidates=None):
    """Re-check every row in the batch and persist the results. Returns the candidate list.

    The whole batch is re-checked rather than the single row that changed, because one
    correction can change another row's verdict: fixing a typo in row 3's address can turn
    row 9 into a duplicate of it, and clearing row 3's duplicate has to clear row 9's too.
    Validating only the edited row would leave the other one showing a stale error.

    One bulk_update for whatever actually changed, so re-validating a 500-row batch after a
    single edit is one write, not 500.
    """
    if candidates is None:
        candidates = list(batch.candidate_set.filter(is_deleted=False)
                          .order_by('upload_row_number', 'candidate_id'))
    else:
        candidates = list(candidates)

    email_counts = Counter(
        normalize_email(c.email) for c in candidates if (c.email or '').strip()
    )
    # Keyed on (last 4 + normalized name), matching the check in validate_candidate_values.
    aadhaar_counts = Counter(
        identity_key(_values_of(c)) for c in candidates if (c.aadhaar_last4 or '').strip()
    )

    changed = []
    for candidate in candidates:
        status, errors = validate_candidate_values(
            _values_of(candidate), email_counts, raw=candidate.upload_raw,
            aadhaar_counts=aadhaar_counts,
        )
        if candidate.validation_status != status or candidate.validation_errors != errors:
            candidate.validation_status = status
            candidate.validation_errors = errors
            changed.append(candidate)

    if changed:
        Candidate.objects.bulk_update(changed, ['validation_status', 'validation_errors'])
    return candidates


def summarize_candidates(candidates):
    """Total / valid / invalid counts for the review screen's summary cards."""
    total = len(candidates)
    valid = sum(1 for c in candidates if c.validation_status == _VS.OK)
    return {'total': total, 'valid': valid, 'invalid': total - valid}
