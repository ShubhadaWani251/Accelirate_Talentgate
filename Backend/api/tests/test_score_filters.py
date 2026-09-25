"""Section score range filters on All Candidates.

Reported: filtering Logical 0-2 returned a candidate the table then displayed with 4. Two
separate faults produced that, and both are pinned here - the filter has to agree with the
number shown in the row, which is the LATEST attempt's score.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from api.models import AttemptSectionScore, Candidate, ExamAttempt, Invitation

pytestmark = pytest.mark.django_db


@pytest.fixture
def candidate_with_attempts(ta_user, make_batch, make_candidate, get_section):
    """Builds a candidate whose attempts score differently in Logical, newest last."""
    section = get_section('logical')
    batch = make_batch(ta_user)
    counter = {'n': 0}

    def _make(*logical_scores):
        counter['n'] += 1
        candidate = make_candidate(batch, ta_user)
        for index, score in enumerate(logical_scores):
            invitation = Invitation.objects.create(
                candidate=candidate, batch=batch,
                unique_link_token=f'score-filter-{counter["n"]}-{index}',
                link_expired_at=timezone.now() + timedelta(days=1), sent_by=ta_user,
            )
            attempt = ExamAttempt.objects.create(
                candidate=candidate, invitation=invitation,
                status=ExamAttempt.Status.SUBMITTED,
            )
            AttemptSectionScore.objects.create(
                attempt=attempt, section=section, score=score, total_marks=10, cleared=False,
            )
        return candidate

    return _make


def _filtered_ids(client, **params):
    response = client.get('/api/candidates/', params)
    assert response.status_code == 200, response.data
    return {row['candidate_id'] for row in response.data['results']}


class TestSectionScoreFilters:
    def test_a_candidate_is_matched_on_their_latest_attempt_not_an_older_one(
        self, candidate_with_attempts, ta_user, client_for,
    ):
        """The reported bug. An older attempt scored 1, the latest scored 4 - the row shows 4,
        so a 0-2 filter must not return it.
        """
        candidate = candidate_with_attempts(1, 4)

        assert candidate.candidate_id not in _filtered_ids(
            client_for(ta_user), logical_min=0, logical_max=2)

    def test_the_same_candidate_matches_the_range_their_latest_score_is_in(
        self, candidate_with_attempts, ta_user, client_for,
    ):
        candidate = candidate_with_attempts(1, 4)

        assert candidate.candidate_id in _filtered_ids(
            client_for(ta_user), logical_min=3, logical_max=5)

    def test_min_and_max_cannot_be_satisfied_by_different_attempts(
        self, candidate_with_attempts, ta_user, client_for,
    ):
        """The second fault: as two separate filter() calls each opened its own join, so 0-2
        matched purely because one attempt was >= 0 and a different one was <= 2.
        """
        candidate = candidate_with_attempts(0, 9)  # one below the range, one above it

        assert candidate.candidate_id not in _filtered_ids(
            client_for(ta_user), logical_min=0, logical_max=2)

    def test_the_bounds_are_inclusive(self, candidate_with_attempts, ta_user, client_for):
        at_floor = candidate_with_attempts(0)
        at_ceiling = candidate_with_attempts(2)

        matched = _filtered_ids(client_for(ta_user), logical_min=0, logical_max=2)
        assert {at_floor.candidate_id, at_ceiling.candidate_id} <= matched

    def test_a_lone_minimum_works_without_a_maximum(
        self, candidate_with_attempts, ta_user, client_for,
    ):
        low = candidate_with_attempts(1)
        high = candidate_with_attempts(8)

        matched = _filtered_ids(client_for(ta_user), logical_min=5)
        assert high.candidate_id in matched
        assert low.candidate_id not in matched

    def test_a_candidate_with_no_attempt_is_excluded(
        self, ta_user, make_batch, make_candidate, client_for, get_section,
    ):
        get_section('logical')
        candidate = make_candidate(make_batch(ta_user), ta_user)

        # No score in the section at all - they cannot be inside a 0-2 range.
        assert candidate.candidate_id not in _filtered_ids(
            client_for(ta_user), logical_min=0, logical_max=2)

    def test_a_candidate_appears_only_once_despite_several_attempts(
        self, candidate_with_attempts, ta_user, client_for,
    ):
        # The old spelling joined a row per attempt; without DISTINCT that duplicated the
        # candidate into the table.
        candidate = candidate_with_attempts(1, 1, 1)

        response = client_for(ta_user).get('/api/candidates/',
                                            {'logical_min': 0, 'logical_max': 2})
        ids = [row['candidate_id'] for row in response.data['results']]
        assert ids.count(candidate.candidate_id) == 1


@pytest.fixture
def candidate_with_overall(ta_user, make_batch, make_candidate):
    """A candidate whose attempts earned the given MARKS, newest last.

    candidate.overall_score is set deliberately out of step with them, because that is the state
    live data is actually in - it is a denormalised percentage, and the filter used to read it.
    """
    batch = make_batch(ta_user)
    counter = {'n': 0}

    def _make(*marks, stored_overall_score=None):
        counter['n'] += 1
        candidate = make_candidate(batch, ta_user)
        for index, earned in enumerate(marks):
            invitation = Invitation.objects.create(
                candidate=candidate, batch=batch,
                unique_link_token=f'overall-filter-{counter["n"]}-{index}',
                link_expired_at=timezone.now() + timedelta(days=1), sent_by=ta_user,
            )
            ExamAttempt.objects.create(
                candidate=candidate, invitation=invitation,
                status=ExamAttempt.Status.SUBMITTED,
                total_marks_earned=earned, total_marks=40,
                overall_score=round(earned * 100 / 40, 2),
            )
        if stored_overall_score is not None:
            Candidate.objects.filter(pk=candidate.pk).update(
                overall_score=stored_overall_score)
        return candidate

    return _make


class TestOverallMarksFilter:
    def test_it_filters_on_MARKS_not_the_stored_percentage(
        self, candidate_with_overall, ta_user, client_for,
    ):
        """The reported bug. The Overall column renders "11/40"; typing 0-12 to catch that 11
        used to match against candidate.overall_score, which for the same row is 27.50.
        """
        candidate = candidate_with_overall(11)

        assert candidate.candidate_id in _filtered_ids(
            client_for(ta_user), score_min=0, score_max=12)

    def test_the_old_percentage_range_no_longer_matches(
        self, candidate_with_overall, ta_user, client_for,
    ):
        """11 marks out of 40 is 27.5%. A 20-30 range meant that row before; it must not now,
        or the filter is still reading percentages.
        """
        candidate = candidate_with_overall(11)

        assert candidate.candidate_id not in _filtered_ids(
            client_for(ta_user), score_min=20, score_max=30)

    def test_it_uses_the_latest_attempt_not_an_older_one(
        self, candidate_with_overall, ta_user, client_for,
    ):
        candidate = candidate_with_overall(2, 30)  # older scored 2, latest scored 30

        matched_low = _filtered_ids(client_for(ta_user), score_min=0, score_max=5)
        matched_high = _filtered_ids(client_for(ta_user), score_min=25, score_max=35)

        assert candidate.candidate_id not in matched_low
        assert candidate.candidate_id in matched_high

    def test_a_stale_stored_overall_score_is_ignored(
        self, candidate_with_overall, ta_user, client_for,
    ):
        """Live data has rows where candidate.overall_score disagrees with the latest attempt -
        one reads 3/40 on screen while the stored figure still says 40.00 from an earlier
        sitting. The attempt is the truth, because the attempt is what the table renders.
        """
        candidate = candidate_with_overall(3, stored_overall_score=40)

        assert candidate.candidate_id in _filtered_ids(
            client_for(ta_user), score_min=0, score_max=5)
        assert candidate.candidate_id not in _filtered_ids(
            client_for(ta_user), score_min=35, score_max=45)

    def test_min_and_max_cannot_be_satisfied_by_different_attempts(
        self, candidate_with_overall, ta_user, client_for,
    ):
        candidate = candidate_with_overall(0, 39)

        assert candidate.candidate_id not in _filtered_ids(
            client_for(ta_user), score_min=0, score_max=5)

    def test_bounds_are_inclusive(self, candidate_with_overall, ta_user, client_for):
        at_floor = candidate_with_overall(0)
        at_ceiling = candidate_with_overall(5)

        matched = _filtered_ids(client_for(ta_user), score_min=0, score_max=5)
        assert {at_floor.candidate_id, at_ceiling.candidate_id} <= matched

    def test_a_candidate_who_never_sat_it_is_excluded(
        self, ta_user, make_batch, make_candidate, client_for,
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user)

        assert candidate.candidate_id not in _filtered_ids(
            client_for(ta_user), score_min=0, score_max=5)

    def test_a_candidate_appears_only_once(
        self, candidate_with_overall, ta_user, client_for,
    ):
        candidate = candidate_with_overall(3, 3, 3)

        response = client_for(ta_user).get('/api/candidates/',
                                            {'score_min': 0, 'score_max': 5})
        ids = [row['candidate_id'] for row in response.data['results']]
        assert ids.count(candidate.candidate_id) == 1
