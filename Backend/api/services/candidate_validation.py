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
    'first_name': 'First Name',
    'last_name': 'Last Name',
    'email': 'Email',
    'phone': 'Mobile',
    'aadhaar_number': 'Aadhaar Number',
    'college_name': 'College Name',
    'degree': 'Degree',
    'stream': 'Stream',
    'percentage': 'Percentage',
    'passing_out_year': 'Passing Out Year',
    'location': 'Location',
}

_AADHAAR_RE = re.compile(r'^\d{12}$')
_MOBILE_STRIP_RE = re.compile(r'[\s\-().]')
_MOBILE_RE = re.compile(r'^\+?\d{10,15}$')

_VS = Candidate.ValidationStatus


def normalize_email(value):
    return (value or '').strip().lower()


def is_valid_email(value):
    try:
        django_validate_email((value or '').strip())
    except DjangoValidationError:
        return False
    return True


def is_valid_mobile(value):
    return bool(_MOBILE_RE.match(_MOBILE_STRIP_RE.sub('', (value or '').strip())))


def validate_candidate_values(values, email_counts=None):
    """Check one row. Returns (validation_status, errors).

    `errors` is every problem found, in the order they're reported on screen:
    [{'field': 'Email', 'message': 'Email "x" is not a valid address.'}, ...]. The returned
    status is the FIRST error's category (or OK) - it drives the status pill and the
    finalize gate, while the list drives the Errors column.

    `email_counts` is a Counter of normalized emails across the whole batch; a row whose
    address appears more than once is flagged. Duplicates are scoped to the batch on purpose:
    the same person legitimately reappears in a later batch, but twice in one upload is a
    mistake in the sheet.
    """
    errors = []
    statuses = []

    def fail(status, field, message):
        statuses.append(status)
        errors.append({'field': field, 'message': message})

    first_name = (values.get('first_name') or '').strip()
    if not first_name:
        fail(_VS.MISSING_NAME, 'First Name', 'Name is required.')

    email = (values.get('email') or '').strip()
    if not email:
        fail(_VS.MISSING_EMAIL, 'Email', 'Email is required.')
    elif not is_valid_email(email):
        fail(_VS.INVALID_EMAIL, 'Email', f'"{email}" is not a valid email address.')
    elif email_counts and email_counts.get(normalize_email(email), 0) > 1:
        fail(_VS.DUPLICATE_EMAIL, 'Email',
             f'"{email}" appears more than once in this batch.')

    aadhaar = (values.get('aadhaar_number') or '').strip()
    if not aadhaar:
        fail(_VS.MISSING_AADHAAR, 'Aadhaar Number', 'Aadhaar Number is required.')
    elif not _AADHAAR_RE.match(aadhaar):
        fail(_VS.INVALID_AADHAAR, 'Aadhaar Number',
             'Aadhaar Number must be exactly 12 digits.')

    college = (values.get('college_name') or '').strip()
    if not college:
        fail(_VS.MISSING_COLLEGE, 'College Name', 'College Name is required.')

    # Mobile is an optional column - blank is fine, but a value that's there has to be usable.
    mobile = (values.get('phone') or '').strip()
    if mobile and not is_valid_mobile(mobile):
        fail(_VS.INVALID_MOBILE, 'Mobile',
             'Mobile must be 10-15 digits (an optional +country code is allowed).')

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

    changed = []
    for candidate in candidates:
        status, errors = validate_candidate_values(_values_of(candidate), email_counts)
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
