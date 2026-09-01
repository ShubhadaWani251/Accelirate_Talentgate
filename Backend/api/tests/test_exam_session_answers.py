"""services/exam_session.py's answer-saving, added alongside the candidate exam UI's
section-per-page view and Mark for Review toggle:

  - save_answer must let selecting an option and marking-for-review vary independently.
  - build_session_state must surface the review flag to the frontend.

Per-section time limits were tried and then deliberately removed - sections stay on separate
pages, but only the overall exam countdown governs timing.
"""
import pytest

from api.models import ExamAnswer, ExamAttempt, Question, QuestionBankSection
from api.services import exam_session

pytestmark = pytest.mark.django_db


@pytest.fixture
def section():
    return QuestionBankSection.objects.create(section_name='Logical & Analytical Reasoning',
                                              section_key='logical')


@pytest.fixture
def question(section):
    return Question.objects.create(
        question_code='Q-EXAM-1', section=section, question_text='2 + 2 = ?',
        option_a='3', option_b='4', option_c='5', option_d='6', correct_option='B',
        difficulty=Question.Difficulty.EASY,
    )


@pytest.fixture
def attempt_with_answer(ta_user, make_batch, make_candidate, make_invitation, question):
    batch = make_batch(ta_user, logical_questions=1, quantitative_questions=0,
                       verbal_questions=0, programming_questions=0, exam_duration_minutes=20)
    candidate = make_candidate(batch, ta_user)
    invitation = make_invitation(candidate, ta_user)
    attempt = ExamAttempt.objects.create(
        candidate=candidate, invitation=invitation, status=ExamAttempt.Status.IN_PROGRESS,
    )
    ExamAnswer.objects.create(attempt=attempt, question=question)
    return attempt


class TestSaveAnswerAndReviewFlagAreIndependent:
    def test_selecting_an_option_does_not_touch_an_existing_review_flag(
        self, attempt_with_answer, question
    ):
        exam_session.save_answer(attempt_with_answer, question.question_id, 'B',
                                 marked_for_review=True)
        answer = exam_session.save_answer(attempt_with_answer, question.question_id, 'A')
        assert answer.selected_option == 'A'
        assert answer.marked_for_review is True

    def test_toggling_the_review_flag_alongside_the_current_selection_keeps_it(
        self, attempt_with_answer, question
    ):
        # selected_option has no "leave as-is" sentinel (unlike time_spent_seconds/
        # marked_for_review) - it's always written, so a review-only toggle has to resend the
        # candidate's current selection rather than omit it. This is the contract the frontend's
        # Mark for Review button relies on.
        exam_session.save_answer(attempt_with_answer, question.question_id, 'B')
        answer = exam_session.save_answer(attempt_with_answer, question.question_id, 'B',
                                          marked_for_review=True)
        assert answer.selected_option == 'B'
        assert answer.marked_for_review is True

    def test_unmarking_clears_the_flag(self, attempt_with_answer, question):
        exam_session.save_answer(attempt_with_answer, question.question_id, None,
                                 marked_for_review=True)
        answer = exam_session.save_answer(attempt_with_answer, question.question_id, None,
                                          marked_for_review=False)
        assert answer.marked_for_review is False


class TestBuildSessionStateIncludesTheReviewFlag:
    def test_each_question_carries_its_review_flag(self, attempt_with_answer, question):
        exam_session.save_answer(attempt_with_answer, question.question_id, 'B',
                                 marked_for_review=True)
        state = exam_session.build_session_state(attempt_with_answer)

        logical = next(s for s in state['sections'] if s['key'] == 'logical')
        assert logical['questions'][0]['marked_for_review'] is True
