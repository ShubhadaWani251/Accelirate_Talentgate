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
from datetime import datetime

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email as django_validate_email
from django.utils import timezone

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
    'date_of_birth': 'Date of Birth',
}

_AADHAAR_RE = re.compile(r'^\d{4}$')
# DD/MM/YYYY is the documented format; the hyphenated variant and the two shapes Excel's own
# native date cells stringify to (see excel_upload._cell_to_text) are accepted too.
_DOB_FORMATS = ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d')
# Nothing born before this is a plausible candidate for an entry-level hiring pipeline - same
# spirit as _MIN_YEAR/_MAX_YEAR below, catching a mis-typed year rather than enforcing an age
# policy.
_MIN_DOB_YEAR = 1940
# The actual age policy, unlike _MIN_DOB_YEAR above: a candidate must be an adult. Checked
# against the real current date (see _age_in_years), not a fixed cutoff year, so this is always
# "18 today" rather than silently going stale.
_MIN_CANDIDATE_AGE_YEARS = 18


def clamp_aadhaar_to_last4(value):
    """Keep at most the last 4 characters of whatever was typed/pasted.

    aadhaar_last4 is a database varchar(4). Nothing enforces that length before a write reaches
    the two places a candidate's Aadhaar value is actually SET - the bulk upload
    (services/excel_upload.py) and the inline row-edit (views/batches.BatchCandidateRowView) -
    both call the ORM directly rather than going through a serializer, so Django's own
    max_length validation never runs. A recruiter pasting a full 12-digit Aadhaar number (the
    format every external HR export still uses, and what candidates were asked for before this
    field was cut down to a suffix) raised a raw DataError that rolled back the ENTIRE upload
    transaction - not just that one row - discarding every other candidate in the same file
    behind an unhelpful "could not read that file" message.

    Truncating to the LAST 4 characters, not rejecting outright, matches how this system already
    treats a full number: migration 0013 truncated every existing full Aadhaar number in the
    database the same way when this field was first cut down. A well-formed 12-digit number
    becomes a valid 4-digit suffix and passes validation normally; genuine garbage (letters, too
    short) still fails _AADHAAR_RE afterward exactly as it did before - this only prevents the
    crash, it does not loosen what counts as valid.
    """
    return (value or '')[-4:]
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


def parse_dob_text(text):
    """Parse a Date of Birth cell/field into a date, or None if it isn't one.

    DD/MM/YYYY is the documented format (the upload template and every edit form use it), with
    a couple of lenient variants: a hyphenated typing of the same format, and whatever str()
    produces for a cell Excel already parsed as a native date - openpyxl hands those back as
    datetime objects, which excel_upload._cell_to_text stringifies to 'YYYY-MM-DD HH:MM:SS' or
    'YYYY-MM-DD' rather than losing them just because the column happened to be date-formatted.
    """
    text = (text or '').strip()
    if not text:
        return None
    for fmt in _DOB_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _age_in_years(dob, as_of):
    """Whole years elapsed from dob to as_of, on the ordinary "birthday" definition - someone
    turns 18 on their 18th birthday itself, not the day after.
    """
    years = as_of.year - dob.year
    if (as_of.month, as_of.day) < (dob.month, dob.day):
        years -= 1
    return years


def identity_key(values):
    """The composite key that identifies a candidate across uploads and batches.

    Only the last 4 Aadhaar digits are stored, and 4 digits is far too weak to identify anyone
    on its own - there are 10,000 possible values, so in a 50-row batch there is roughly a 1-in-8
    chance two unrelated candidates share a suffix. Pairing the digits with date of birth makes a
    collision require both, which is rare enough to treat as the same person. Name is
    deliberately NOT part of this key (it used to be) - a person's name is typed inconsistently
    across uploads (spelling, order, a maiden name) far more often than their Aadhaar+DOB pair
    changes, so keying on name produced missed matches that keying on DOB does not.

    `values` is the dict shape returned by _values_of / used by validate_candidate_values -
    'date_of_birth' is a `date` (already parsed), not raw text.
    """
    last4 = (values.get('aadhaar_last4') or '').strip()
    dob = values.get('date_of_birth')
    return (last4, dob.isoformat() if dob else '')


def candidate_identity_key(candidate):
    """identity_key for a saved Candidate row."""
    return identity_key({
        'aadhaar_last4': candidate.aadhaar_last4,
        'date_of_birth': candidate.date_of_birth,
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

    # --- Aadhaar (required, exactly 4 digits, unique within the batch) --------------
    # Only the last 4 digits are held (see models/candidate.py), so on their own they are a
    # weak identifier - 10,000 possible values means unrelated people collide routinely. The
    # within-batch duplicate check is therefore on (last 4 + date of birth), not the digits
    # alone; flagging every shared suffix would bury the reviewer in false duplicates. The
    # cross-batch cooling-off check keys on the same pair - see services/duplicate_check.py.
    aadhaar = (values.get('aadhaar_last4') or '').strip()
    dob = values.get('date_of_birth')
    if not aadhaar:
        fail(_VS.MISSING_AADHAAR, 'Aadhaar Last 4 Digits', 'Aadhaar last 4 digits required')
    elif not _AADHAAR_RE.match(aadhaar):
        fail(_VS.INVALID_AADHAAR, 'Aadhaar Last 4 Digits', 'Must be exactly 4 digits')
    # dob required here too: without it, every row sharing just the Aadhaar suffix collapses
    # onto the same (last4, '') key and would incorrectly flag each other as duplicates - the
    # missing-DOB check below already reports the real problem for those rows.
    elif dob and aadhaar_counts and aadhaar_counts.get(identity_key(values), 0) > 1:
        fail(_VS.DUPLICATE_AADHAAR, 'Aadhaar Last 4 Digits',
             'Same Date of Birth and Aadhaar last 4 digits already appear in this batch')

    # --- Date of Birth (required, DD/MM/YYYY, plausible range) -----------------------
    # The other half of the identity key (see identity_key above).
    raw_dob = (raw.get('date_of_birth') or '').strip()
    if not raw_dob and dob is None:
        fail(_VS.MISSING_DOB, 'Date of Birth', 'Date of Birth required')
    elif raw_dob and dob is None:
        fail(_VS.INVALID_DOB, 'Date of Birth', 'Must be a valid date (DD/MM/YYYY)')
    elif dob is not None and dob > timezone.now().date():
        fail(_VS.INVALID_DOB, 'Date of Birth', 'Cannot be in the future')
    elif dob is not None and dob.year < _MIN_DOB_YEAR:
        fail(_VS.INVALID_DOB, 'Date of Birth', f'Must be after {_MIN_DOB_YEAR}')
    elif dob is not None and _age_in_years(dob, timezone.now().date()) < _MIN_CANDIDATE_AGE_YEARS:
        fail(_VS.UNDERAGE, 'Date of Birth',
             f'Candidate must be at least {_MIN_CANDIDATE_AGE_YEARS} years old')

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
    # Keyed on (last 4 + date of birth), matching the check in validate_candidate_values. Rows
    # with no DOB yet are left out entirely - validate_candidate_values only consults this
    # counter when a row's OWN dob is present too, so a DOB-less row could never be usefully
    # counted here anyway, and leaving it in would make every DOB-less row sharing an Aadhaar
    # suffix collapse onto the same (last4, '') key.
    aadhaar_counts = Counter(
        identity_key(_values_of(c)) for c in candidates
        if (c.aadhaar_last4 or '').strip() and c.date_of_birth
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
