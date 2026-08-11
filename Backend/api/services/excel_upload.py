from openpyxl import Workbook, load_workbook

from api.models import Candidate
from api.services.duplicate_check import run_duplicate_check

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


def stage_candidates_from_workbook(batch, file_obj, user, cooling_off_months=3):
    """Parse the uploaded workbook and create one Candidate row per data row, attached
    to `batch` (expected to be in Batch.Status.DRAFT), each validated and duplicate-checked.
    """
    created = []
    for data in parse_uploaded_workbook(file_obj):
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
        run_duplicate_check(candidate, cooling_off_months=cooling_off_months)
        created.append(candidate)
    return created
