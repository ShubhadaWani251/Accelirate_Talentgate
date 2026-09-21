"""The three business rules that were stored-but-not-enforced, fixed together:

  ISS-15  a candidate who already PASSED could be re-invited, and the retake's result would
          silently overwrite the pass (services/invites.assert_candidate_can_be_reinvited).
  ISS-16  Question.difficulty was filterable in the bank but ignored when drawing a paper, so
          two candidates in one batch could get papers of different difficulty and be judged
          against the same cutoff (services/question_selection.difficulty_quotas).
  ISS-17  Question.marks was collected, validated and displayed but never scored - a 2-mark
          question counted exactly as much as a 1-mark one
          (services/exam_session._grade_sections).

Every question in the real bank is currently worth 1 mark, so the ISS-17 tests below deliberately
create weighted questions: with a uniform bank the old and new arithmetic agree on every value
and nothing here would actually be exercised.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from api.models import Candidate, ExamAnswer, ExamAttempt, Invitation, Question, QuestionBankSection
from api.services import exam_session
from api.services.invites import (
    CandidateNotInvitableError, assert_candidate_can_be_reinvited, create_single_reinvite,
)
from api.services.question_selection import (
    InsufficientQuestionsError, difficulty_quotas, select_questions_for_attempt,
)

pytestmark = pytest.mark.django_db
def set_cutoff(batch, value, *section_keys):
    """Revise a batch's cutoff for one or more sections.

    A cutoff lives on the batch's BatchSection row now, not on a Batch column - so a test that
    revises one has to go through the same place the application does.
    """
    from api.models import BatchSection
    BatchSection.objects.filter(
        batch=batch, section__section_key__in=section_keys,
    ).update(cutoff=value)


def section_score(attempt, section_key):
    """The AttemptSectionScore row for one section of an attempt, or None."""
    return attempt.section_scores.filter(section__section_key=section_key).first()


# --------------------------------------------------------------------------------- ISS-15

class TestPassedCandidatesCannotBeReinvited:
    def test_the_service_refuses_a_candidate_who_passed(self, ta_user, make_batch, make_candidate):
        candidate = make_candidate(make_batch(ta_user), ta_user, result=Candidate.Result.PASS)

        with pytest.raises(CandidateNotInvitableError):
            create_single_reinvite(candidate, ta_user)

        assert not Invitation.objects.filter(candidate=candidate).exists()

    @pytest.mark.parametrize('result', [Candidate.Result.FAIL, Candidate.Result.PENDING])
    def test_failed_and_pending_candidates_are_still_invitable(
        self, ta_user, make_batch, make_candidate, result,
    ):
        # A deliberate second chance after a fail, or a first invite for someone who never sat
        # it, are both legitimate TA decisions - only a PASS is protected.
        candidate = make_candidate(make_batch(ta_user), ta_user, result=result)

        assert_candidate_can_be_reinvited(candidate)
        assert create_single_reinvite(candidate, ta_user).candidate_id == candidate.candidate_id

    def test_the_single_endpoint_returns_400_and_sends_nothing(
        self, ta_user, make_batch, make_candidate, client_for,
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user, result=Candidate.Result.PASS)

        response = client_for(ta_user).post(
            '/api/candidates/%d/resend-invite/' % candidate.candidate_id, {}, format='json',
        )

        assert response.status_code == 400
        assert 'already passed' in response.data['detail']
        assert not Invitation.objects.filter(candidate=candidate).exists()

    def test_bulk_skips_the_passed_candidate_and_still_sends_to_the_rest(
        self, ta_user, make_batch, make_candidate, client_for,
    ):
        # The important half of the rule: one already-passed row in a selection must not cancel
        # everyone else's link, which is why this is a skip rather than the hard stop a batch
        # status refusal gets.
        batch = make_batch(ta_user)
        passed = make_candidate(batch, ta_user, result=Candidate.Result.PASS)
        pending = make_candidate(batch, ta_user)

        response = client_for(ta_user).post(
            '/api/candidates/resend-invite/',
            {'candidate_ids': [passed.candidate_id, pending.candidate_id]},
            format='json',
        )

        assert response.status_code == 200, response.data
        assert response.data['sent_count'] == 1
        assert response.data['skipped_count'] == 1
        assert 'already passed' in response.data['detail']
        assert Invitation.objects.filter(candidate=pending).count() == 1
        assert not Invitation.objects.filter(candidate=passed).exists()

    def test_bulk_where_everyone_passed_is_a_400(
        self, ta_user, make_batch, make_candidate, client_for,
    ):
        batch = make_batch(ta_user)
        ids = [make_candidate(batch, ta_user, result=Candidate.Result.PASS).candidate_id
               for _ in range(2)]

        response = client_for(ta_user).post(
            '/api/candidates/resend-invite/', {'candidate_ids': ids}, format='json',
        )

        assert response.status_code == 400
        assert 'already passed' in response.data['detail']
        assert not Invitation.objects.exists()


# --------------------------------------------------------------------------------- ISS-16

class TestDifficultyQuotas:
    def test_quotas_always_sum_to_the_requested_count(self):
        # Largest-remainder's whole point: the floors alone lose seats, and a paper that is one
        # question short would be a far worse bug than an unbalanced one.
        assert sum(difficulty_quotas({'Easy': 21, 'Medium': 24}, 10).values()) == 10
        assert sum(difficulty_quotas({'Easy': 1, 'Medium': 1, 'Hard': 1}, 7).values()) == 7
        assert sum(difficulty_quotas({'Easy': 50}, 13).values()) == 13

    def test_quotas_follow_the_pool_proportions(self):
        # 30 Easy / 10 Medium is 3:1, so 20 questions split 15/5 exactly.
        assert difficulty_quotas({'Easy': 30, 'Medium': 10}, 20) == {'Easy': 15, 'Medium': 5}

    def test_a_difficulty_the_bank_does_not_stock_gets_no_quota(self):
        # The real bank holds no Hard questions at all, so this is the live case, not a corner.
        assert 'Hard' not in difficulty_quotas({'Easy': 28, 'Medium': 18}, 10)

    def test_no_quota_can_exceed_its_own_pool(self):
        # Drawing the entire pool is the boundary where an off-by-one would make random.sample
        # raise instead of returning a paper.
        assert difficulty_quotas({'Easy': 3, 'Medium': 2}, 5) == {'Easy': 3, 'Medium': 2}

    def test_an_off_choices_difficulty_does_not_crash_selection(self):
        # Paper selection runs when a candidate presses Start, so a stray difficulty value has
        # to degrade to "sorts last", never to an exception that makes the exam unreachable.
        quota = difficulty_quotas({'Easy': 2, 'Impossible': 2}, 3)
        assert sum(quota.values()) == 3
        assert quota['Impossible'] <= 2


class TestPapersAreDifficultyBalanced:
    @pytest.fixture
    def stocked_section(self, get_section):
        section = get_section('logical')
        for n in range(12):
            # 3:1 Easy:Medium, so a 4-question paper must be exactly 3 Easy + 1 Medium.
            difficulty = Question.Difficulty.MEDIUM if n % 4 == 3 else Question.Difficulty.EASY
            Question.objects.create(
                question_code='Q-BAL-%d' % n, section=section, question_text='q%d' % n,
                option_a='a', option_b='b', correct_option='A', difficulty=difficulty,
            )
        return section

    def _batch(self, make_batch, ta_user):
        return make_batch(ta_user, logical_questions=4, quantitative_questions=0,
                          verbal_questions=0, programming_questions=0)

    def test_every_draw_has_the_same_difficulty_mix(
        self, stocked_section, ta_user, make_batch,
    ):
        batch = self._batch(make_batch, ta_user)

        mixes = set()
        for _ in range(12):
            questions = select_questions_for_attempt(batch)['logical']
            assert len(questions) == 4
            mixes.add(tuple(sorted(q.difficulty for q in questions)))

        # One mix across every draw - the gap ISS-16 described was two candidates in the same
        # batch getting papers of different difficulty.
        assert mixes == {('Easy', 'Easy', 'Easy', 'Medium')}

    def test_which_questions_are_drawn_is_still_random(
        self, stocked_section, ta_user, make_batch,
    ):
        # Balancing difficulty must not accidentally make the paper deterministic - that would
        # trade one problem for a worse one (answer-sharing within an open window).
        batch = self._batch(make_batch, ta_user)
        papers = {
            tuple(q.question_id for q in select_questions_for_attempt(batch)['logical'])
            for _ in range(12)
        }
        assert len(papers) > 1

    def test_a_section_short_of_questions_still_raises(
        self, stocked_section, ta_user, make_batch,
    ):
        batch = make_batch(ta_user, logical_questions=99, quantitative_questions=0,
                           verbal_questions=0, programming_questions=0)

        with pytest.raises(InsufficientQuestionsError) as exc:
            select_questions_for_attempt(batch)

        # Counts the whole section pool, not one difficulty bucket.
        assert exc.value.available == 12


# --------------------------------------------------------------------------------- ISS-17

@pytest.fixture
def weighted_attempt(ta_user, make_batch, make_candidate, make_invitation, get_section):
    """One section, three questions: a 5-mark one and two 1-mark ones.

    Chosen so marks and answer counts disagree about who passed a 50% cutoff - getting only the
    heavy question right is 5/7 of the marks but 1/3 of the questions.
    """
    section = get_section('logical')
    questions = [
        Question.objects.create(
            question_code='Q-MK-%d' % n, section=section, question_text='q%d' % n,
            option_a='a', option_b='b', correct_option='A',
            difficulty=Question.Difficulty.EASY, marks=marks,
        )
        for n, marks in enumerate([5, 1, 1])
    ]
    batch = make_batch(
        ta_user, logical_questions=3, quantitative_questions=0, verbal_questions=0,
        programming_questions=0, logical_cutoff=Decimal('50.00'),
    )
    candidate = make_candidate(batch, ta_user)
    invitation = Invitation.objects.create(
        candidate=candidate, batch=batch, unique_link_token='marks-token',
        link_expired_at=timezone.now() + timedelta(days=1), sent_by=ta_user,
    )
    attempt = ExamAttempt.objects.create(
        candidate=candidate, invitation=invitation, status=ExamAttempt.Status.IN_PROGRESS,
        started_at=timezone.now(),
    )
    for question in questions:
        ExamAnswer.objects.create(attempt=attempt, question=question)
    return attempt, questions


def _answer(attempt, question, option):
    ExamAnswer.objects.filter(attempt=attempt, question=question).update(
        selected_option=option, answered_at=timezone.now(),
    )


class TestMarksAreWeightedInScoring:
    def test_the_heavy_question_alone_clears_a_50_percent_cutoff(self, weighted_attempt):
        attempt, questions = weighted_attempt
        _answer(attempt, questions[0], 'A')   # 5 marks, correct
        _answer(attempt, questions[1], 'B')   # 1 mark, wrong
        _answer(attempt, questions[2], 'B')   # 1 mark, wrong

        exam_session.finalize_attempt(attempt, outcome='submitted')
        attempt.refresh_from_db()

        # 5 of 7 marks = 71%, over the 50% cutoff. Counting answers instead gives 1 of 3 = 33%,
        # which is what this used to do - the candidate failed for getting the hardest question
        # right and the two throwaways wrong.
        assert section_score(attempt, 'logical').score == 5
        assert section_score(attempt, 'logical').cleared is True
        assert attempt.overall_score == Decimal('71.43')
        assert attempt.candidate.result == Candidate.Result.PASS

    def test_the_two_light_questions_alone_do_not_clear_it(self, weighted_attempt):
        attempt, questions = weighted_attempt
        _answer(attempt, questions[0], 'B')   # 5 marks, wrong
        _answer(attempt, questions[1], 'A')   # 1 mark, correct
        _answer(attempt, questions[2], 'A')   # 1 mark, correct

        exam_session.finalize_attempt(attempt, outcome='submitted')
        attempt.refresh_from_db()

        # The mirror image: 2 of 7 marks = 29%, a fail - where counting answers gives 2 of 3 =
        # 67% and a pass.
        assert section_score(attempt, 'logical').score == 2
        assert section_score(attempt, 'logical').cleared is False
        assert attempt.candidate.result == Candidate.Result.FAIL

    def test_total_correct_stays_a_question_count(self, weighted_attempt):
        attempt, questions = weighted_attempt
        _answer(attempt, questions[0], 'A')
        _answer(attempt, questions[1], 'A')
        _answer(attempt, questions[2], 'B')

        exam_session.finalize_attempt(attempt, outcome='submitted')
        attempt.refresh_from_db()

        # Three different units on one row, which is exactly why they have three names.
        assert attempt.total_correct == 2          # questions right
        assert attempt.total_marks_earned == 6     # marks earned
        assert attempt.total_marks == 7            # marks available

    def test_an_unanswered_paper_scores_zero_without_dividing_by_zero(self, weighted_attempt):
        attempt, _questions = weighted_attempt

        exam_session.finalize_attempt(attempt, outcome='submitted')
        attempt.refresh_from_db()

        assert attempt.total_marks_earned == 0
        assert attempt.total_marks == 7
        assert attempt.overall_score == Decimal('0.00')
        assert section_score(attempt, 'logical').cleared is False

    def test_regrading_after_a_cutoff_change_uses_the_same_weighting(self, weighted_attempt):
        attempt, questions = weighted_attempt
        _answer(attempt, questions[1], 'A')   # 1 of 7 marks = 14%
        exam_session.finalize_attempt(attempt, outcome='submitted')
        attempt.refresh_from_db()
        assert section_score(attempt, 'logical').cleared is False

        batch = attempt.invitation.batch
        set_cutoff(batch, Decimal('10.00'), 'logical')

        assert exam_session.regrade_attempt(attempt, batch) is True
        attempt.refresh_from_db()
        # Re-graded against the marks percentage, not a recount of answers.
        assert section_score(attempt, 'logical').cleared is True
        assert attempt.total_marks_earned == 1
        assert attempt.total_marks == 7


class TestMarksSurfaceToTheApi:
    def test_candidate_detail_reports_marks_not_question_counts(
        self, weighted_attempt, ta_user, client_for,
    ):
        attempt, questions = weighted_attempt
        _answer(attempt, questions[0], 'A')
        exam_session.finalize_attempt(attempt, outcome='submitted')

        response = client_for(ta_user).get(
            '/api/candidates/%d/' % attempt.candidate_id,
        )

        assert response.status_code == 200, response.data
        # The "x/y" pair a TA reads is marks over marks - the batch's 3-question config is not
        # a valid denominator for a 7-mark paper.
        assert response.data['total_marks_earned'] == 5
        assert response.data['overall_total'] == 7
        assert response.data['total_correct'] == 1
        logical = next(r for r in response.data['section_results'] if r['score'] is not None)
        assert (logical['score'], logical['total']) == (5, 7)
