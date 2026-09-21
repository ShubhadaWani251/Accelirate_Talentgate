"""The All Candidates export - services/excel_upload.generate_candidates_workbook.

Covers the section-wise score columns specifically: they have to sit alongside Overall Score
(not replace it), and a candidate with no attempt yet must export as blank, not zero - a zero
would misreport "took it and scored nothing" for someone who never sat the assessment.
"""
import pytest

from api.models import AttemptSectionScore, ExamAttempt, QuestionBankSection
from api.services.excel_upload import export_columns, generate_candidates_workbook

pytestmark = pytest.mark.django_db


def _row_dict(ws, row_idx=2):
    headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    values = [c.value for c in next(ws.iter_rows(min_row=row_idx, max_row=row_idx))]
    return dict(zip(headers, values))


class TestSectionScoreColumns:
    def test_the_export_has_a_column_for_each_section_plus_overall(self, get_section):
        for key in ['logical', 'quantitative', 'verbal', 'programming']:
            get_section(key)
        columns = export_columns(list(QuestionBankSection.objects.all()))

        for col in ['Logical & Analytical Score', 'Quantitative Score', 'Verbal Ability Score',
                    'Programming Score', 'Overall Score']:
            assert col in columns
        # Overall stays last - it's the summary, section scores are the detail behind it.
        assert columns.index('Overall Score') > columns.index('Programming Score')

    def test_a_newly_added_section_gets_its_own_column(self, get_section):
        get_section('logical')
        QuestionBankSection.objects.create(section_name='Data Interpretation',
                                           section_key='data_interp', display_order=50)
        columns = export_columns(list(QuestionBankSection.objects.all()))

        # The point of the whole change: no code anywhere names this section.
        assert 'Data Interpretation Score' in columns
        assert columns.index('Data Interpretation Score') < columns.index('Overall Score')

    def test_a_candidate_with_an_attempt_exports_its_section_scores(
        self, ta_user, make_batch, make_candidate, make_invitation, get_section
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user)
        invitation = make_invitation(candidate, ta_user)
        attempt = ExamAttempt.objects.create(
            candidate=candidate, invitation=invitation, status=ExamAttempt.Status.SUBMITTED,
            total_marks_earned=5, total_marks=8,
            overall_score=62.5,
        )
        for key, score in [('logical', 2), ('quantitative', 1), ('verbal', 2),
                           ('programming', 0)]:
            AttemptSectionScore.objects.create(
                attempt=attempt, section=get_section(key), score=score, total_marks=2,
            )

        wb = generate_candidates_workbook(
            [candidate],
            latest_attempt_fn=lambda c: ExamAttempt.objects.filter(candidate=c).first(),
        )
        row = _row_dict(wb.active)

        assert row['Logical & Analytical Score'] == 2
        assert row['Quantitative Score'] == 1
        assert row['Verbal Ability Score'] == 2
        assert row['Programming Score'] == 0
        assert row['Overall Score'] == 62.5

    def test_a_candidate_with_no_attempt_exports_blank_section_scores_not_zero(
        self, ta_user, make_batch, make_candidate
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user)

        wb = generate_candidates_workbook([candidate], latest_attempt_fn=lambda c: None)
        row = _row_dict(wb.active)

        assert row['Logical & Analytical Score'] is None
        assert row['Quantitative Score'] is None
        assert row['Verbal Ability Score'] is None
        assert row['Programming Score'] is None
