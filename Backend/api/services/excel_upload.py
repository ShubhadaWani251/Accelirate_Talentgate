from django.db import transaction
from openpyxl import Workbook, load_workbook

from api.models import Candidate
from api.services.duplicate_check import preload_duplicate_lookup, run_duplicate_check

TEMPLATE_COLUMNS = [
    'Name', 'Email', 'Aadhaar Number', 'College Name', 'Degree',
    'Stream', 'Percentage', 'Passing Out Year', 'Location',
]

_HEADER_MAP = {
    'name': 'name',
    'email': 'email',
    'aadhaar number': 'aadhaar_number',
    'aadhaar': 'aadhaar_number',
    'college name': 'college_name',
    'college': 'college_name',
    'degree': 'degree',
    'stream': 'stream',
    'percentage': 'percentage',
    'passing out year': 'passing_out_year',
    'location': 'location',
}


def generate_template_workbook():
    wb = Workbook()
    ws = wb.active
    ws.title = 'Candidates'
    ws.append(TEMPLATE_COLUMNS)
    ws.append(['Jane Doe', 'jane.doe@example.com', '123456789012', 'XYZ College',
               'B.Tech', 'Computer Science', '78.5', '2025', 'Pune'])
    return wb


EXPORT_COLUMNS = [
    'Name', 'Email', 'Batch Name', 'College', 'Degree', 'Stream', 'Percentage',
    'Passing Out Year', 'Location', 'Status', 'Result', 'Overall Score',
]


def generate_candidates_workbook(candidates, latest_attempt_fn):
    """Export for the All Candidates screen. latest_attempt_fn resolves a candidate's
    latest ExamAttempt (or None) - passed in rather than imported, to avoid a serializers
    -> services import cycle.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = 'Candidates'
    ws.append(EXPORT_COLUMNS)
    for candidate in candidates:
        attempt = latest_attempt_fn(candidate)
        overall_score = attempt.overall_score if attempt else candidate.overall_score
        ws.append([
            candidate.full_name,
            candidate.email,
            candidate.batch.batch_name,
            candidate.college_name,
            candidate.degree,
            candidate.stream,
            float(candidate.percentage) if candidate.percentage is not None else None,
            candidate.passing_out_year,
            candidate.location,
            candidate.get_status_display(),
            candidate.get_result_display(),
            float(overall_score) if overall_score is not None else None,
        ])
    return wb


def _normalize_header(value):
    return str(value).strip().lower() if value is not None else ''


def parse_uploaded_workbook(file_obj):
    """Yields one dict per data row (1-indexed row_number matching the spreadsheet,
    header = row 1). Unrecognized columns are ignored; missing columns just come back
    as empty strings, surfaced later as validation errors rather than parse failures.
    """
    wb = load_workbook(file_obj, data_only=True, read_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)

    header_row = next(rows, None)
    if not header_row:
        return

    field_by_col = {}
    for idx, header in enumerate(header_row):
        field = _HEADER_MAP.get(_normalize_header(header))
        if field:
            field_by_col[idx] = field

    for row_number, row in enumerate(rows, start=2):
        if row is None or all(cell in (None, '') for cell in row):
            continue
        data = {'row_number': row_number}
        for idx, field in field_by_col.items():
            value = row[idx] if idx < len(row) else None
            data[field] = str(value).strip() if value is not None else ''
        yield data


def _to_float(value):
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _to_int(value):
    try:
        return int(float(value)) if value else None
    except ValueError:
        return None


@transaction.atomic
def stage_candidates_from_workbook(batch, file_obj, user, cooling_off_months=3):
    """Parse the uploaded workbook and create one Candidate row per data row, attached
    to `batch` (expected to be in Batch.Status.DRAFT), each validated and duplicate-checked.

    Wrapped in one transaction so a failure partway through (e.g. a bad row triggering an
    unexpected DB error) can't leave a batch half-populated - the caller's `except Exception`
    around this call sees a clean rollback either way. Rows are parsed into a list up front
    (rather than streamed) so every Aadhaar number is known before duplicate-checking starts,
    letting preload_duplicate_lookup fetch every existing match in one query instead of one
    query per row.
    """
    rows = list(parse_uploaded_workbook(file_obj))
    duplicate_lookup = preload_duplicate_lookup(
        (row.get('aadhaar_number') or '').strip() for row in rows
    )

    created = []
    for data in rows:
        name = data.get('name', '') or ''
        name_parts = name.split(None, 1)
        first_name = name_parts[0] if name_parts else ''
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        email = data.get('email', '') or ''
        aadhaar = data.get('aadhaar_number', '') or ''
        college = data.get('college_name', '') or ''

        if not first_name:
            validation_status = Candidate.ValidationStatus.MISSING_NAME
        elif not email:
            validation_status = Candidate.ValidationStatus.MISSING_EMAIL
        elif not aadhaar:
            validation_status = Candidate.ValidationStatus.MISSING_AADHAAR
        elif not college:
            validation_status = Candidate.ValidationStatus.MISSING_COLLEGE
        else:
            validation_status = Candidate.ValidationStatus.OK

        candidate = Candidate.objects.create(
            batch=batch,
            upload_row_number=data['row_number'],
            first_name=first_name,
            last_name=last_name or None,
            email=email,
            aadhaar_number=aadhaar,
            college_name=college or None,
            degree=data.get('degree') or None,
            stream=data.get('stream') or None,
            percentage=_to_float(data.get('percentage')),
            passing_out_year=_to_int(data.get('passing_out_year')),
            location=data.get('location') or None,
            validation_status=validation_status,
            created_by=user,
        )
        run_duplicate_check(candidate, cooling_off_months=cooling_off_months, existing_lookup=duplicate_lookup)
        if candidate.aadhaar_number:
            # Keep the lookup current so a later row in this SAME upload that repeats an
            # Aadhaar number is still caught as a duplicate against this one, not just against
            # candidates that existed before the upload started.
            duplicate_lookup[candidate.aadhaar_number] = candidate
        created.append(candidate)
    return created
