"""Section score range filters on All Candidates.

Reported: filtering Logical 0-2 returned a candidate the table then displayed with 4. Two
separate faults produced that, and both are pinned here - the filter has to agree with the
number shown in the row, which is the LATEST attempt's score.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from api.models import AttemptSectionScore, ExamAttempt, Invitation

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
