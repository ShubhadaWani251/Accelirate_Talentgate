"""Finalize refuses a batch whose sections cannot supply the questions they ask for.

A section added from Question Bank Management is included in new batches immediately and starts
with no questions, so a batch could be created, finalized and invited asking for 10 questions
from an empty section. The shortfall then surfaced at exam start, as a 409 to the CANDIDATE,
after they had installed Safe Exam Browser, granted camera access and photographed their Aadhaar
card - with nothing they could do about it and nobody having told the admin.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from api.models import Batch, BatchSection, Candidate, Question
from api.services.question_selection import section_supply_shortfalls

pytestmark = pytest.mark.django_db

# make_batch builds BatchSection rows only for the four STANDARD_SECTIONS, off legacy
# <key>_questions kwargs. These tests are about sections outside that set, so they zero those
# kwargs (leaving a batch with no rows at all) and attach their own.
NO_STANDARD_SECTIONS = dict(
    logical_questions=0, quantitative_questions=0,
    verbal_questions=0, programming_questions=0,
)


def _add_questions(section, count):
    Question.objects.bulk_create([
        Question(
            section=section, question_code=f'{section.section_key}-{i}',
            question_text=f'{section.section_key} question {i}?',
            option_a='A', option_b='B', option_c='C', option_d='D', correct_option='A',
            difficulty=Question.Difficulty.EASY, marks=1,
            status=Question.Status.ACTIVE,
        )
        for i in range(count)
    ])


@pytest.fixture
def batch_with_sections(ta_user, make_batch, get_section):
    """A batch running exactly the given {section_key: question_count}, and nothing else."""
    def _make(specs, status=Batch.Status.IN_PROGRESS, **kwargs):
        batch = make_batch(ta_user, status=status, **NO_STANDARD_SECTIONS, **kwargs)
        for section_key, question_count in specs.items():
            BatchSection.objects.create(
                batch=batch, section=get_section(section_key),
                question_count=question_count, cutoff=50,
            )
        return batch
    return _make


class TestSectionSupplyShortfalls:
    def test_a_section_with_no_questions_is_reported(self, batch_with_sections):
        batch = batch_with_sections({'empty_topic': 10})

        shortfalls = section_supply_shortfalls(batch)

        assert [(s['section_key'], s['required'], s['available']) for s in shortfalls] == [
            ('empty_topic', 10, 0),
        ]

    def test_a_fully_stocked_batch_reports_nothing(self, batch_with_sections, get_section):
        _add_questions(get_section('stocked'), 12)
        batch = batch_with_sections({'stocked': 10})

        assert section_supply_shortfalls(batch) == []

    def test_exactly_enough_is_enough(self, batch_with_sections, get_section):
        _add_questions(get_section('exact'), 10)
        batch = batch_with_sections({'exact': 10})

        assert section_supply_shortfalls(batch) == []

    def test_only_ACTIVE_questions_count(self, batch_with_sections, get_section):
        """The same pool select_questions_for_attempt draws from - deactivating questions after
        a batch exists is exactly how a previously-fine batch goes short.
        """
        section = get_section('halfstocked')
        _add_questions(section, 10)
        Question.objects.filter(section=section).update(status=Question.Status.INACTIVE)
        batch = batch_with_sections({'halfstocked': 10})

        assert section_supply_shortfalls(batch)[0]['available'] == 0

    def test_every_short_section_is_reported_not_just_the_first(self, batch_with_sections):
        """select_questions_for_attempt raises on the first one because it has an exam to serve.
        An admin would rather fix all of them in one pass.
        """
        batch = batch_with_sections({'short_a': 5, 'short_b': 5})

        assert {s['section_key'] for s in section_supply_shortfalls(batch)} == {
            'short_a', 'short_b',
        }

    def test_a_section_asking_for_zero_questions_is_never_short(self, batch_with_sections):
        batch = batch_with_sections({'zero': 0})

        assert section_supply_shortfalls(batch) == []


class TestFinalizeRefusesAnUnrunnableBatch:
    def _draft(self, batch_with_sections, get_section, stocked):
        _add_questions(get_section('finalizable'), stocked)
        now = timezone.now()
        return batch_with_sections(
            {'finalizable': 10}, status=Batch.Status.DRAFT,
            link_valid_from=now + timedelta(days=1),
            link_valid_until=now + timedelta(days=2),
        )

    def _candidate(self, batch, ta_user, make_candidate):
        candidate = make_candidate(batch, ta_user)
        Candidate.objects.filter(pk=candidate.pk).update(
            validation_status=Candidate.ValidationStatus.OK,
        )
        return candidate

    def _finalize(self, client, batch, candidate):
        return client.post(
            f'/api/batches/{batch.batch_id}/finalize/',
            {'candidate_ids': [candidate.candidate_id]}, format='json',
        )

    def test_finalize_is_refused_when_a_section_is_short(
        self, batch_with_sections, get_section, ta_user, make_candidate, client_for,
    ):
        batch = self._draft(batch_with_sections, get_section, stocked=3)
        candidate = self._candidate(batch, ta_user, make_candidate)

        response = self._finalize(client_for(ta_user), batch, candidate)

        assert response.status_code == 400, response.data
        assert 'more questions than the bank can supply' in response.data['detail']

    def test_the_refusal_names_the_section_and_the_numbers(
        self, batch_with_sections, get_section, ta_user, make_candidate, client_for,
    ):
        batch = self._draft(batch_with_sections, get_section, stocked=3)
        candidate = self._candidate(batch, ta_user, make_candidate)

        response = self._finalize(client_for(ta_user), batch, candidate)

        assert response.data['section_shortfalls'] == [{
            'section_key': 'finalizable', 'section_name': 'Finalizable',
            'required': 10, 'available': 3,
        }]

    def test_the_batch_stays_a_draft_and_nobody_is_invited(
        self, batch_with_sections, get_section, ta_user, make_candidate, client_for,
    ):
        batch = self._draft(batch_with_sections, get_section, stocked=3)
        candidate = self._candidate(batch, ta_user, make_candidate)

        self._finalize(client_for(ta_user), batch, candidate)

        batch.refresh_from_db()
        assert batch.status == Batch.Status.DRAFT
        assert not batch.invitation_set.exists()

    def test_a_fully_stocked_batch_still_finalizes(
        self, batch_with_sections, get_section, ta_user, make_candidate, client_for,
    ):
        """The gate must not stand in the way of the normal path."""
        batch = self._draft(batch_with_sections, get_section, stocked=10)
        candidate = self._candidate(batch, ta_user, make_candidate)

        response = self._finalize(client_for(ta_user), batch, candidate)

        assert response.status_code == 200, response.data
        batch.refresh_from_db()
        assert batch.status != Batch.Status.DRAFT
