"""Reviewing a cutoff change before applying it.

Reported as "there is no clear option to review or validate an assessment after changing
cut-off marks or sections". Changing a cutoff silently re-grades everyone who has already sat
the exam, and the only way to find out what that did was to do it and read the columns after.

The endpoint runs the REAL regrade inside a transaction and rolls it back. These tests are
mostly about that rollback actually holding - a preview with a side effect is worse than no
preview at all - and about the preview agreeing with what applying then does.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from api.models import Candidate, ExamAnswer, ExamAttempt, Invitation, Question
from api.services import exam_session

pytestmark = pytest.mark.django_db


@pytest.fixture
def graded_batch(admin_user, make_batch, make_candidate, get_section):
    """One section of two 1-mark questions, and two candidates: one scored 2/2, one 1/2.

    At a 100% cutoff only the first clears; at 50% both do. That one gap is what every
    assertion below moves across.
    """
    section = get_section('logical')
    questions = [
        Question.objects.create(
            question_code=f'Q-CP-{n}', section=section, question_text=f'q{n}',
            option_a='a', option_b='b', correct_option='A',
            difficulty=Question.Difficulty.EASY, marks=1,
        )
        for n in range(2)
    ]
    batch = make_batch(
        admin_user, logical_questions=2, quantitative_questions=0, verbal_questions=0,
        programming_questions=0, logical_cutoff=Decimal('100.00'),
    )
    for index, correct_answers in enumerate([2, 1]):
        candidate = make_candidate(batch, admin_user, first_name=f'Cand{index}')
        invitation = Invitation.objects.create(
            candidate=candidate, batch=batch, unique_link_token=f'cp-token-{index}',
            link_expired_at=timezone.now() + timedelta(days=1), sent_by=admin_user,
        )
        attempt = ExamAttempt.objects.create(
            candidate=candidate, invitation=invitation,
            status=ExamAttempt.Status.IN_PROGRESS, started_at=timezone.now(),
        )
        for position, question in enumerate(questions):
            ExamAnswer.objects.create(
                attempt=attempt, question=question,
                selected_option='A' if position < correct_answers else 'B',
                answered_at=timezone.now(),
            )
        exam_session.finalize_attempt(attempt, 'submitted')
    return batch


def _preview(client, batch, cutoff):
    return client.post(
        f'/api/batches/{batch.batch_id}/cutoff-preview/',
        {'section_cutoffs': [{'section_key': 'logical', 'cutoff': cutoff}]},
        format='json',
    )


def _results(batch):
    return sorted(batch.candidate_set.values_list('result', flat=True))


class TestThePreviewChangesNothing:
    def test_results_are_untouched_afterwards(self, admin_user, client_for, graded_batch):
        """The whole contract. A preview that leaked would re-grade a live cohort on a
        button that promised to do nothing."""
        before = _results(graded_batch)

        response = _preview(client_for(admin_user), graded_batch, 50)

        assert response.status_code == 200
        assert _results(graded_batch) == before

    def test_the_cutoff_itself_is_untouched(self, admin_user, client_for, graded_batch):
        _preview(client_for(admin_user), graded_batch, 50)

        graded_batch.refresh_from_db()
        cutoffs = {bs.section.section_key: bs.cutoff
                   for bs in graded_batch.sections.select_related('section').all()}
        assert cutoffs['logical'] == Decimal('100.00')


class TestThePreviewReportsWhatWouldHappen:
    def test_it_counts_who_moves(self, admin_user, client_for, graded_batch):
        """Dropping the cutoff to 50% should carry the 1/2 candidate from fail to pass."""
        response = _preview(client_for(admin_user), graded_batch, 50)

        body = response.data
        assert body['before']['pass'] == 1 and body['before']['fail'] == 1
        assert body['after']['pass'] == 2 and body['after']['fail'] == 0
        assert body['changed_count'] == 1
        assert body['changed'][0]['from'] == Candidate.Result.FAIL
        assert body['changed'][0]['to'] == Candidate.Result.PASS

    def test_it_names_the_cutoff_being_changed(self, admin_user, client_for, graded_batch):
        body = _preview(client_for(admin_user), graded_batch, 50).data

        assert body['cutoff_changes'] == [{
            'section_key': 'logical', 'section_name': 'Logical & Analytical',
            'from': '100.00', 'to': '50',
        }]

    def test_an_unchanged_cutoff_reports_no_changes(self, admin_user, client_for, graded_batch):
        """What the modal keys off to say "nothing to apply" instead of offering a no-op."""
        body = _preview(client_for(admin_user), graded_batch, 100).data

        assert body['cutoff_changes'] == []
        assert body['changed_count'] == 0

    def test_the_preview_matches_what_applying_actually_does(self, admin_user, client_for,
                                                             graded_batch):
        """The property the whole feature rests on: predict, then do, then compare."""
        client = client_for(admin_user)
        predicted = _preview(client, graded_batch, 50).data

        client.patch(
            f'/api/batches/{graded_batch.batch_id}/',
            {'section_cutoffs': [{'section_key': 'logical', 'cutoff': 50}]},
            format='json',
        )

        actual = {}
        for result in _results(graded_batch):
            actual[result] = actual.get(result, 0) + 1
        for band, count in actual.items():
            assert predicted['after'][band] == count, f'{band} was mispredicted'


class TestWhoMayPreview:
    def test_a_ta_may_not(self, ta_user, client_for, graded_batch):
        """Same gate as changing a cutoff for real - a preview reveals the whole cohort's
        results under a hypothetical policy, which is the policy call itself."""
        response = _preview(client_for(ta_user), graded_batch, 50)

        assert response.status_code == 403

    def test_a_malformed_cutoff_is_rejected_without_saving(self, admin_user, client_for,
                                                           graded_batch):
        before = _results(graded_batch)

        response = _preview(client_for(admin_user), graded_batch, 150)

        assert response.status_code == 400
        assert _results(graded_batch) == before

    def test_a_missing_payload_is_rejected(self, admin_user, client_for, graded_batch):
        response = client_for(admin_user).post(
            f'/api/batches/{graded_batch.batch_id}/cutoff-preview/', {}, format='json',
        )

        assert response.status_code == 400
