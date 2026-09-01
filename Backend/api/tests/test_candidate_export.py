"""The All Candidates export - services/excel_upload.generate_candidates_workbook.

Covers the section-wise score columns specifically: they have to sit alongside Overall Score
(not replace it), and a candidate with no attempt yet must export as blank, not zero - a zero
would misreport "took it and scored nothing" for someone who never sat the assessment.
"""
import pytest

from api.models import ExamAttempt
from api.services.excel_upload import EXPORT_COLUMNS, generate_candidates_workbook

pytestmark = pytest.mark.django_db


def _row_dict(ws, row_idx=2):
    headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    values = [c.value for c in next(ws.iter_rows(min_row=row_idx, max_row=row_idx))]
    return dict(zip(headers, values))


class TestSectionScoreColumns:
    def test_the_export_has_a_column_for_each_section_plus_overall(self):
        for col in ['Logical Score', 'Quantitative Score', 'Verbal Score',
                    'Programming Score', 'Overall Score']:
            assert col in EXPORT_COLUMNS
        # Overall stays last - it's the summary, section scores are the detail behind it.
        assert EXPORT_COLUMNS.index('Overall Score') > EXPORT_COLUMNS.index('Programming Score')

    def test_a_candidate_with_an_attempt_exports_its_section_scores(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user)
        invitation = make_invitation(candidate, ta_user)
        ExamAttempt.objects.create(
            candidate=candidate, invitation=invitation, status=ExamAttempt.Status.SUBMITTED,
            logical_score=2, quantitative_score=1, verbal_score=2, programming_score=0,
            overall_score=62.5,
        )

        wb = generate_candidates_workbook(
            [candidate],
            latest_attempt_fn=lambda c: ExamAttempt.objects.filter(candidate=c).first(),
        )
        row = _row_dict(wb.active)

        assert row['Logical Score'] == 2
        assert row['Quantitative Score'] == 1
        assert row['Verbal Score'] == 2
        assert row['Programming Score'] == 0
        assert row['Overall Score'] == 62.5

    def test_a_candidate_with_no_attempt_exports_blank_section_scores_not_zero(
        self, ta_user, make_batch, make_candidate
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user)

        wb = generate_candidates_workbook([candidate], latest_attempt_fn=lambda c: None)
        row = _row_dict(wb.active)

        assert row['Logical Score'] is None
        assert row['Quantitative Score'] is None
        assert row['Verbal Score'] is None
        assert row['Programming Score'] is None
