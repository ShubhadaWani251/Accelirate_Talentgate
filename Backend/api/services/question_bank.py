from django.db import transaction
from openpyxl import Workbook, load_workbook

from api.models import Question, QuestionBankSection
from api.serializers.question import generate_question_code

TEMPLATE_COLUMNS = [
    'Section', 'Question Text', 'Option A', 'Option B', 'Option C', 'Option D',
    'Correct Option', 'Difficulty', 'Marks',
]

_HEADER_MAP = {
    'section': 'section_key',
    'question text': 'question_text',
    'question': 'question_text',
    'option a': 'option_a',
    'option b': 'option_b',
    'option c': 'option_c',
    'option d': 'option_d',
    'correct option': 'correct_option',
    'correct answer': 'correct_option',
    'difficulty': 'difficulty',
    'marks': 'marks',
}

_VALID_DIFFICULTIES = {c[0] for c in Question.Difficulty.choices}
_VALID_OPTIONS = {'A', 'B', 'C', 'D'}


def generate_question_template_workbook():
    wb = Workbook()
    ws = wb.active
    ws.title = 'Questions'
    ws.append(TEMPLATE_COLUMNS)
    ws.append([
        'logical', 'If all Bloops are Razzies and all Razzies are Lazzies, are all Bloops '
                   'definitely Lazzies?',
        'Yes', 'No', 'Cannot be determined', 'Only sometimes',
        'A', 'Medium', '1',
    ])
    # Second sample row demonstrates that the Section column also accepts the full display
    # name (as seen in the app), not just the short internal key used in the row above.
    ws.append([
        'Verbal Ability', 'Choose the word most similar in meaning to "Candid".',
        'Honest', 'Secretive', 'Aggressive', 'Cautious',
        'A', 'Easy', '1',
    ])
    return wb


def _normalize_header(value):
    return str(value).strip().lower() if value is not None else ''


def _parse_question_workbook(file_obj):
    """Yields one dict per data row (1-indexed row_number matching the spreadsheet,
    header = row 1) - same shape/behavior as services/excel_upload.py's candidate parser.
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


@transaction.atomic
def import_questions_from_workbook(file_obj, user):
    """Parse the uploaded workbook and create one active Question per valid data row.
    Unlike the candidate bulk-upload pipeline, there's no staging/duplicate-review step -
    a bad row is just reported back as an error and skipped, everything else is created
    immediately. Wrapped in one transaction so a mid-file DB error rolls back cleanly rather
    than leaving a half-imported file.
    """
    # Keyed by both the internal section_key ("verbal") and the human-readable section_name
    # ("verbal ability", lowercased) - the template/UI shows section_name everywhere, so a user
    # typing what they actually see should match just as well as the internal key.
    sections_by_key = {}
    for s in QuestionBankSection.objects.all():
        sections_by_key[s.section_key.lower()] = s
        sections_by_key[s.section_name.lower()] = s

    created = []
    errors = []
    for data in _parse_question_workbook(file_obj):
        row_number = data['row_number']
        section_key = (data.get('section_key') or '').strip().lower()
        section = sections_by_key.get(section_key)
        if not section:
            errors.append({'row': row_number, 'message': f'Unknown section "{section_key}".'})
            continue

        question_text = data.get('question_text') or ''
        option_a = data.get('option_a') or ''
        option_b = data.get('option_b') or ''
        if not question_text or not option_a or not option_b:
            errors.append({'row': row_number,
                            'message': 'Question Text, Option A, and Option B are required.'})
            continue

        correct_option = (data.get('correct_option') or '').strip().upper()
        if correct_option not in _VALID_OPTIONS:
            errors.append({'row': row_number, 'message': 'Correct Option must be A, B, C, or D.'})
            continue
        option_c = data.get('option_c') or ''
        option_d = data.get('option_d') or ''
        if correct_option == 'C' and not option_c:
            errors.append({'row': row_number, 'message': 'Correct Option is C but Option C is empty.'})
            continue
        if correct_option == 'D' and not option_d:
            errors.append({'row': row_number, 'message': 'Correct Option is D but Option D is empty.'})
            continue

        difficulty = (data.get('difficulty') or '').strip().title()
        if difficulty not in _VALID_DIFFICULTIES:
            errors.append({'row': row_number,
                            'message': f'Difficulty must be one of {", ".join(sorted(_VALID_DIFFICULTIES))}.'})
            continue

        try:
            marks = int(float(data.get('marks') or 1))
        except ValueError:
            errors.append({'row': row_number, 'message': 'Marks must be a number.'})
            continue

        question = Question.objects.create(
            question_code=generate_question_code(),
            section=section,
            question_text=question_text,
            option_a=option_a,
            option_b=option_b,
            option_c=option_c or None,
            option_d=option_d or None,
            correct_option=correct_option,
            difficulty=difficulty,
            marks=marks,
            status=Question.Status.ACTIVE,
            created_by=user,
        )
        created.append(question)

    return created, errors
