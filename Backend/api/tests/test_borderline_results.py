"""Borderline results, and the human decision that resolves them.

The rule, as specified: a candidate who missed a section cutoff by at most 1 MARK, in at most 3
sections, is BORDERLINE rather than a fail - the system refuses to call it and puts them in front
of a TA or Admin, who decides Pass or Fail from Candidate Details.

Every missed section has to be within that 1 mark. Someone 1 short in one section and 4 short in
another did not "just barely" miss, and is a plain fail - that distinction is the thing most
worth getting wrong, so it is tested from both sides.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from api.models import (
    AuditLog, Candidate, ExamAnswer, ExamAttempt, Invitation, Question, QuestionBankSection,
)
from api.services import exam_session
from api.services.candidate_history import build_candidate_history

pytestmark = pytest.mark.django_db

SECTIONS = ['logical', 'quantitative', 'verbal', 'programming']


@pytest.fixture
def bank():
    """Ten 1-mark questions in each of the four sections, so "1 mark" and "1 question" coincide
    and a scenario reads as the number of right answers it is.
    """
    questions = {}
    for key in SECTIONS:
        section = QuestionBankSection.objects.create(
            section_name=key.title(), section_key=key,
        )
        questions[key] = [
            Question.objects.create(
                question_code=f'Q-{key[:4].upper()}-{n}', section=section,
                question_text=f'{key} {n}', option_a='a', option_b='b', correct_option='A',
                difficulty=Question.Difficulty.EASY,
            )
            for n in range(10)
        ]
    return questions


@pytest.fixture
def make_graded_attempt(bank, ta_user, make_batch, make_candidate):
    """Build and finalize an attempt where `correct` says how many of each section's 10
    questions the candidate got right. Every cutoff is 50%, so 5 of 10 clears and 4 is exactly
    one mark short.
    """
    counter = {'n': 0}

    def _make(correct, cutoff=Decimal('50.00'), outcome='submitted'):
        counter['n'] += 1
        batch = make_batch(
            ta_user, logical_questions=10, quantitative_questions=10, verbal_questions=10,
            programming_questions=10,
            logical_cutoff=cutoff, quantitative_cutoff=cutoff, verbal_cutoff=cutoff,
            programming_cutoff=cutoff,
        )
        candidate = make_candidate(batch, ta_user)
        invitation = Invitation.objects.create(
            candidate=candidate, batch=batch,
            unique_link_token=f'borderline-token-{counter["n"]}',
            link_expired_at=timezone.now() + timedelta(days=1), sent_by=ta_user,
        )
        attempt = ExamAttempt.objects.create(
            candidate=candidate, invitation=invitation,
            status=ExamAttempt.Status.IN_PROGRESS, started_at=timezone.now(),
        )
        for key in SECTIONS:
            for index, question in enumerate(bank[key]):
                ExamAnswer.objects.create(
                    attempt=attempt, question=question,
                    # 'A' is the correct option; anything else scores zero.
                    selected_option='A' if index < correct[key] else 'B',
                    answered_at=timezone.now(),
                )
        exam_session.finalize_attempt(attempt, outcome=outcome,
                                      reason='tab_switch' if outcome != 'submitted' else None)
        attempt.refresh_from_db()
        candidate.refresh_from_db()
        return attempt, candidate

    return _make


class TestMarksNeededToClear:
    def test_an_exact_percentage(self):
        assert exam_session.marks_needed_to_clear(10, Decimal('50')) == 5

    def test_a_fractional_requirement_rounds_up(self):
        # 45% of 10 is 4.5 marks, and you cannot score half a mark - 5 is the first score that
        # clears. Rounding DOWN here would hand a pass to someone on 4/10 = 40%.
        assert exam_session.marks_needed_to_clear(10, Decimal('45')) == 5

    def test_a_repeating_decimal_boundary(self):
        # 33.33% of 3 marks is 0.9999 - one mark clears it. Float arithmetic is exactly where
        # this kind of boundary goes wrong, which is why the implementation uses Decimal.
        assert exam_session.marks_needed_to_clear(3, Decimal('33.33')) == 1
        assert exam_session.marks_needed_to_clear(3, Decimal('66.67')) == 3

    def test_a_zero_cutoff_needs_nothing(self):
        assert exam_session.marks_needed_to_clear(10, Decimal('0')) == 0


class TestIsBorderline:
    def test_one_section_one_mark_short(self):
        assert exam_session.is_borderline({'logical': 1}) is True

    def test_three_sections_each_one_mark_short(self):
        assert exam_session.is_borderline(
            {'logical': 1, 'quantitative': 1, 'verbal': 1}) is True

    def test_all_four_sections_is_too_many(self):
        # The cap is 3 subjects. Missing every section, however narrowly, is not a near miss.
        assert exam_session.is_borderline(
            {'logical': 1, 'quantitative': 1, 'verbal': 1, 'programming': 1}) is False

    def test_a_section_missed_by_more_than_one_mark_disqualifies_the_whole_thing(self):
        # The decisive case. One section 1 short and another 4 short is a plain fail: EVERY
        # missed section has to be within a mark, or the borderline queue fills with people who
        # were not close.
        assert exam_session.is_borderline({'logical': 1, 'quantitative': 4}) is False

    def test_missing_nothing_is_not_borderline(self):
        # A candidate who cleared everything passed outright and never needs a human decision.
        assert exam_session.is_borderline({}) is False


class TestGradingProducesBorderline:
    def test_one_mark_short_in_one_section(self, make_graded_attempt):
        _attempt, candidate = make_graded_attempt(
            {'logical': 4, 'quantitative': 5, 'verbal': 5, 'programming': 5})
        assert candidate.result == Candidate.Result.BORDERLINE

    def test_one_mark_short_in_three_sections(self, make_graded_attempt):
        _attempt, candidate = make_graded_attempt(
            {'logical': 4, 'quantitative': 4, 'verbal': 4, 'programming': 5})
        assert candidate.result == Candidate.Result.BORDERLINE

    def test_one_mark_short_in_all_four_sections_is_a_fail(self, make_graded_attempt):
        _attempt, candidate = make_graded_attempt(
            {'logical': 4, 'quantitative': 4, 'verbal': 4, 'programming': 4})
        assert candidate.result == Candidate.Result.FAIL

    def test_two_marks_short_anywhere_is_a_fail(self, make_graded_attempt):
        _attempt, candidate = make_graded_attempt(
            {'logical': 3, 'quantitative': 5, 'verbal': 5, 'programming': 5})
        assert candidate.result == Candidate.Result.FAIL

    def test_a_mixed_near_miss_and_bad_miss_is_a_fail(self, make_graded_attempt):
        _attempt, candidate = make_graded_attempt(
            {'logical': 4, 'quantitative': 1, 'verbal': 5, 'programming': 5})
        assert candidate.result == Candidate.Result.FAIL

    def test_clearing_everything_is_still_a_pass(self, make_graded_attempt):
        _attempt, candidate = make_graded_attempt(
            {'logical': 5, 'quantitative': 5, 'verbal': 5, 'programming': 5})
        assert candidate.result == Candidate.Result.PASS

    def test_a_terminated_attempt_is_never_borderline(self, make_graded_attempt):
        # The marks are a textbook borderline, but the attempt ended on a proctoring violation -
        # what failed it was the violation, not the score, so there is nothing for a TA to weigh.
        _attempt, candidate = make_graded_attempt(
            {'logical': 4, 'quantitative': 5, 'verbal': 5, 'programming': 5},
            outcome='terminated',
        )
        assert candidate.result == Candidate.Result.FAIL


class TestDecideResultEndpoint:
    def _url(self, candidate):
        return '/api/candidates/%d/decide-result/' % candidate.candidate_id

    def test_a_ta_can_pass_a_borderline_candidate(
        self, make_graded_attempt, ta_user, client_for,
    ):
        _attempt, candidate = make_graded_attempt(
            {'logical': 4, 'quantitative': 5, 'verbal': 5, 'programming': 5})

        response = client_for(ta_user).post(self._url(candidate), {'result': 'pass'},
                                            format='json')

        assert response.status_code == 200, response.data
        candidate.refresh_from_db()
        assert candidate.result == Candidate.Result.PASS
        assert candidate.result_decided_by_id == ta_user.user_id
        assert candidate.result_decided_at is not None

    def test_an_admin_can_fail_a_borderline_candidate(
        self, make_graded_attempt, admin_user, client_for,
    ):
        _attempt, candidate = make_graded_attempt(
            {'logical': 4, 'quantitative': 5, 'verbal': 5, 'programming': 5})

        response = client_for(admin_user).post(self._url(candidate), {'result': 'fail'},
                                               format='json')

        assert response.status_code == 200, response.data
        candidate.refresh_from_db()
        assert candidate.result == Candidate.Result.FAIL

    def test_a_decision_can_be_changed(self, make_graded_attempt, ta_user, client_for):
        _attempt, candidate = make_graded_attempt(
            {'logical': 4, 'quantitative': 5, 'verbal': 5, 'programming': 5})
        client = client_for(ta_user)
        client.post(self._url(candidate), {'result': 'pass'}, format='json')

        # The candidate is no longer BORDERLINE at this point, so what keeps the endpoint open
        # is result_decided_by being set - a misclick must not be permanent.
        response = client.post(self._url(candidate), {'result': 'fail'}, format='json')

        assert response.status_code == 200, response.data
        candidate.refresh_from_db()
        assert candidate.result == Candidate.Result.FAIL

    def test_a_plain_fail_cannot_be_decided(self, make_graded_attempt, ta_user, client_for):
        _attempt, candidate = make_graded_attempt(
            {'logical': 0, 'quantitative': 0, 'verbal': 0, 'programming': 0})

        response = client_for(ta_user).post(self._url(candidate), {'result': 'pass'},
                                            format='json')

        assert response.status_code == 400
        candidate.refresh_from_db()
        assert candidate.result == Candidate.Result.FAIL

    def test_a_pass_cannot_be_quietly_overturned(
        self, make_graded_attempt, ta_user, client_for,
    ):
        # This endpoint exists to resolve borderline cases, not as a general result override.
        _attempt, candidate = make_graded_attempt(
            {'logical': 5, 'quantitative': 5, 'verbal': 5, 'programming': 5})

        response = client_for(ta_user).post(self._url(candidate), {'result': 'fail'},
                                            format='json')

        assert response.status_code == 400
        candidate.refresh_from_db()
        assert candidate.result == Candidate.Result.PASS

    @pytest.mark.parametrize('value', ['borderline', 'pending', '', None, 'PASS'])
    def test_only_pass_or_fail_are_accepted(
        self, make_graded_attempt, ta_user, client_for, value,
    ):
        _attempt, candidate = make_graded_attempt(
            {'logical': 4, 'quantitative': 5, 'verbal': 5, 'programming': 5})

        response = client_for(ta_user).post(self._url(candidate), {'result': value},
                                            format='json')

        assert response.status_code == 400
        candidate.refresh_from_db()
        assert candidate.result == Candidate.Result.BORDERLINE

    def test_the_decision_is_audited_and_shows_on_the_timeline(
        self, make_graded_attempt, ta_user, client_for,
    ):
        _attempt, candidate = make_graded_attempt(
            {'logical': 4, 'quantitative': 5, 'verbal': 5, 'programming': 5})
        client = client_for(ta_user)
        client.post(self._url(candidate), {'result': 'pass'}, format='json')
        client.post(self._url(candidate), {'result': 'fail'}, format='json')

        rows = AuditLog.objects.filter(
            action_type='result_decided', entity_id=candidate.candidate_id,
        ).order_by('log_id')
        assert [r.action_details['result'] for r in rows] == ['pass', 'fail']
        # The superseded decision survives only here - the candidate row holds the latest one.
        assert rows[1].action_details['previous_result'] == 'pass'

        labels = [e['event'] for e in build_candidate_history(candidate)]
        assert 'Result Decided - Pass' in labels
        assert 'Result Decided - Fail' in labels


class TestADecisionSurvivesARegrade:
    def test_changing_a_cutoff_does_not_overwrite_a_human_decision(
        self, make_graded_attempt, ta_user, client_for,
    ):
        attempt, candidate = make_graded_attempt(
            {'logical': 4, 'quantitative': 5, 'verbal': 5, 'programming': 5})
        client_for(ta_user).post('/api/candidates/%d/decide-result/' % candidate.candidate_id,
                                 {'result': 'pass'}, format='json')

        # Raise the cutoff so the machine would now score this a clear fail.
        batch = attempt.invitation.batch
        batch.logical_cutoff = Decimal('90.00')
        batch.save(update_fields=['logical_cutoff'])
        exam_session.regrade_batch(batch)

        candidate.refresh_from_db()
        attempt.refresh_from_db()
        # The TA's call stands...
        assert candidate.result == Candidate.Result.PASS
        # ...but the attempt's own section flags are still recomputed, so the TA can see the
        # new picture and decide again if they want to.
        assert attempt.logical_cleared is False

    def test_an_undecided_candidate_is_still_regraded_normally(self, make_graded_attempt):
        attempt, candidate = make_graded_attempt(
            {'logical': 4, 'quantitative': 5, 'verbal': 5, 'programming': 5})
        assert candidate.result == Candidate.Result.BORDERLINE

        batch = attempt.invitation.batch
        batch.logical_cutoff = Decimal('40.00')
        batch.save(update_fields=['logical_cutoff'])
        exam_session.regrade_batch(batch)

        candidate.refresh_from_db()
        assert candidate.result == Candidate.Result.PASS


class TestBorderlineSurfacesToTheApi:
    def test_candidate_detail_offers_the_decision(
        self, make_graded_attempt, ta_user, client_for,
    ):
        _attempt, candidate = make_graded_attempt(
            {'logical': 4, 'quantitative': 5, 'verbal': 5, 'programming': 5})

        response = client_for(ta_user).get('/api/candidates/%d/' % candidate.candidate_id)

        assert response.status_code == 200, response.data
        assert response.data['result'] == 'borderline'
        assert response.data['result_display'] == 'Borderline'
        assert response.data['needs_result_decision'] is True
        assert response.data['result_decided_by_name'] is None

    def test_candidate_detail_keeps_offering_it_after_a_decision(
        self, make_graded_attempt, ta_user, client_for,
    ):
        _attempt, candidate = make_graded_attempt(
            {'logical': 4, 'quantitative': 5, 'verbal': 5, 'programming': 5})
        client = client_for(ta_user)
        client.post('/api/candidates/%d/decide-result/' % candidate.candidate_id,
                    {'result': 'pass'}, format='json')

        response = client.get('/api/candidates/%d/' % candidate.candidate_id)

        assert response.data['needs_result_decision'] is True
        assert response.data['result_decided_by_name'] == ta_user.full_name

    def test_a_plain_pass_is_not_offered_a_decision(
        self, make_graded_attempt, ta_user, client_for,
    ):
        _attempt, candidate = make_graded_attempt(
            {'logical': 5, 'quantitative': 5, 'verbal': 5, 'programming': 5})

        response = client_for(ta_user).get('/api/candidates/%d/' % candidate.candidate_id)

        assert response.data['needs_result_decision'] is False

    def test_the_batch_counts_borderline_candidates(
        self, make_graded_attempt, ta_user, client_for,
    ):
        attempt, _candidate = make_graded_attempt(
            {'logical': 4, 'quantitative': 5, 'verbal': 5, 'programming': 5})
        batch = attempt.invitation.batch

        response = client_for(ta_user).get('/api/batches/%d/' % batch.batch_id)

        assert response.status_code == 200, response.data
        # A real count now, not the hardcoded 0 this field returned before the rule existed.
        assert response.data['borderline_count'] == 1
        assert response.data['pass_count'] == 0
        assert response.data['fail_count'] == 0

    def test_deciding_moves_the_candidate_out_of_the_borderline_count(
        self, make_graded_attempt, ta_user, client_for,
    ):
        attempt, candidate = make_graded_attempt(
            {'logical': 4, 'quantitative': 5, 'verbal': 5, 'programming': 5})
        client = client_for(ta_user)
        client.post('/api/candidates/%d/decide-result/' % candidate.candidate_id,
                    {'result': 'pass'}, format='json')

        response = client.get('/api/batches/%d/' % attempt.invitation.batch.batch_id)

        assert response.data['borderline_count'] == 0
        assert response.data['pass_count'] == 1


class TestLoweringACutoffTakesEffect:
    """Reported live: a candidate showing "2/10, cutoff 20%, Not Cleared" after the cutoff was
    lowered to 20 - which reads as the cutoff change having done nothing.

    The cause was that the attempt had been TERMINATED, and regrade skipped every non-submitted
    attempt outright. Candidate Details renders each section's CURRENT cutoff next to a Cleared
    flag stored at submit time, so the two drifted apart and contradicted each other on screen.
    """

    def test_lowering_a_cutoff_clears_the_sections_it_should(self, make_graded_attempt):
        attempt, candidate = make_graded_attempt(
            {'logical': 2, 'quantitative': 3, 'verbal': 1, 'programming': 0})
        assert attempt.logical_cleared is False

        batch = attempt.invitation.batch
        batch.logical_cutoff = Decimal('20.00')
        batch.quantitative_cutoff = Decimal('20.00')
        batch.save(update_fields=['logical_cutoff', 'quantitative_cutoff'])
        exam_session.regrade_batch(batch)

        attempt.refresh_from_db()
        candidate.refresh_from_db()
        # 2/10 is exactly 20%, and the cutoff is met at exactly the cutoff - a boundary that has
        # to clear, or a TA setting 20% to admit a 2/10 finds it still rejected.
        assert attempt.logical_cleared is True
        assert attempt.quantitative_cleared is True
        # Verbal and programming are still below their untouched 50%, so this stays a fail.
        assert candidate.result == Candidate.Result.FAIL

    def test_a_terminated_attempts_sections_are_recomputed_but_it_still_fails(
        self, make_graded_attempt,
    ):
        attempt, candidate = make_graded_attempt(
            {'logical': 2, 'quantitative': 3, 'verbal': 1, 'programming': 0},
            outcome='terminated',
        )
        batch = attempt.invitation.batch
        for field in ('logical_cutoff', 'quantitative_cutoff', 'verbal_cutoff',
                      'programming_cutoff'):
            setattr(batch, field, Decimal('0.00'))
        batch.save()

        exam_session.regrade_batch(batch)

        attempt.refresh_from_db()
        candidate.refresh_from_db()
        # Every section now clears at a 0% cutoff, so the table agrees with the cutoff beside it...
        assert attempt.logical_cleared is True
        assert attempt.programming_cleared is True
        # ...but the attempt was terminated for a proctoring violation, and no cutoff change can
        # resurrect that. This is the half that must NOT move.
        assert candidate.result == Candidate.Result.FAIL

    def test_an_in_progress_attempt_is_still_skipped(
        self, bank, ta_user, make_batch, make_candidate,
    ):
        batch = make_batch(ta_user, logical_questions=10, quantitative_questions=10,
                           verbal_questions=10, programming_questions=10)
        candidate = make_candidate(batch, ta_user)
        invitation = Invitation.objects.create(
            candidate=candidate, batch=batch, unique_link_token='in-progress-token',
            link_expired_at=timezone.now() + timedelta(days=1), sent_by=ta_user,
        )
        attempt = ExamAttempt.objects.create(
            candidate=candidate, invitation=invitation,
            status=ExamAttempt.Status.IN_PROGRESS, started_at=timezone.now(),
        )

        assert exam_session.regrade_attempt(attempt, batch) is False
        attempt.refresh_from_db()
        assert attempt.logical_cleared is None
