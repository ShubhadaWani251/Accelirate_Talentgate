"""Batch configuration validation, in particular the link window vs the exam duration."""

from datetime import timedelta

import pytest
from django.utils import timezone

from api.models import Batch
from api.serializers.batch import BatchSerializer


def payload(window_minutes, duration_minutes, **overrides):
    start = timezone.now() + timedelta(days=1)
    data = {
        'batch_name': 'Validation Test',
        'college_name': 'Test College',
        'link_valid_from': start,
        'link_valid_until': start + timedelta(minutes=window_minutes),
        'exam_duration_minutes': duration_minutes,
        'logical_questions': 2,
        'quantitative_questions': 2,
        'verbal_questions': 2,
        'programming_questions': 2,
        'logical_cutoff': 70,
        'quantitative_cutoff': 70,
        'verbal_cutoff': 70,
        'programming_cutoff': 70,
    }
    data.update(overrides)
    return data


class TestLinkWindowMustCoverTheExam:
    def test_a_window_shorter_than_the_exam_is_rejected(self, db):
        """The real case this came from: a 26-minute window on a 45-minute exam."""
        serializer = BatchSerializer(data=payload(window_minutes=26, duration_minutes=45))
        assert not serializer.is_valid()
        assert 'link_valid_until' in serializer.errors

    def test_the_error_names_both_numbers(self, db):
        """So the TA can see what to change, rather than being told only that it is wrong."""
        serializer = BatchSerializer(data=payload(window_minutes=26, duration_minutes=45))
        serializer.is_valid()
        message = str(serializer.errors['link_valid_until'][0])
        assert '26' in message
        assert '45' in message

    def test_a_window_exactly_the_exam_length_is_allowed(self, db):
        """The boundary is inclusive: equal is sufficient, since the exam clock runs from
        started_at and is not truncated by link expiry.
        """
        serializer = BatchSerializer(data=payload(window_minutes=45, duration_minutes=45))
        assert serializer.is_valid(), serializer.errors

    def test_a_longer_window_is_allowed(self, db):
        serializer = BatchSerializer(data=payload(window_minutes=60 * 24 * 7,
                                                  duration_minutes=45))
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.parametrize('window,duration', [(1, 2), (44, 45), (0, 1)])
    def test_every_short_window_is_caught(self, db, window, duration):
        serializer = BatchSerializer(data=payload(window_minutes=window,
                                                  duration_minutes=duration))
        assert not serializer.is_valid()

    def test_end_before_start_is_still_rejected_first(self, db):
        """The pre-existing check must keep its own clearer message rather than being
        replaced by the duration one.
        """
        serializer = BatchSerializer(data=payload(window_minutes=-10, duration_minutes=45))
        assert not serializer.is_valid()
        assert 'Must be after Link Valid From.' in str(serializer.errors['link_valid_until'][0])


class TestValidationOnUpdate:
    def test_shortening_the_window_on_an_existing_batch_is_rejected(self, ta_user, make_batch):
        """The duration comes from the instance when it is not in the payload, so editing only
        the end time is still checked against the exam it has to cover.
        """
        batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        serializer = BatchSerializer(
            batch,
            data={'link_valid_until': batch.link_valid_from + timedelta(minutes=10)},
            partial=True,
        )
        assert not serializer.is_valid()
        assert 'link_valid_until' in serializer.errors

    def test_lengthening_the_exam_beyond_the_window_is_rejected(self, ta_user, make_batch):
        """The other direction: the window is untouched but the exam no longer fits inside it."""
        batch = make_batch(ta_user, status=Batch.Status.DRAFT,
                           link_valid_until=timezone.now() + timedelta(minutes=30))
        serializer = BatchSerializer(batch, data={'exam_duration_minutes': 120}, partial=True)
        assert not serializer.is_valid()
        assert 'link_valid_until' in serializer.errors

    def test_an_unrelated_edit_is_not_blocked(self, ta_user, make_batch):
        """A batch whose window already covers its exam must stay editable - the check must not
        fire on every partial update that happens to touch neither field.
        """
        batch = make_batch(ta_user, status=Batch.Status.DRAFT)
        serializer = BatchSerializer(batch, data={'batch_name': 'Renamed'}, partial=True)
        assert serializer.is_valid(), serializer.errors


class TestOverHttp:
    def test_creating_a_batch_with_a_short_window_returns_400(self, ta_user, client_for):
        response = client_for(ta_user).post(
            '/api/batches/', payload(window_minutes=26, duration_minutes=45), format='json',
        )
        assert response.status_code == 400
        assert 'link_valid_until' in response.data

    def test_a_valid_batch_is_still_created(self, ta_user, client_for):
        response = client_for(ta_user).post(
            '/api/batches/', payload(window_minutes=120, duration_minutes=45), format='json',
        )
        assert response.status_code in (200, 201), response.data


class TestExistingBadDataIsGrandfathered:
    """One live batch predates this validation with a 26-minute window on a 45-minute exam.

    Its status permits only the section cutoffs to be edited. If the check ran unconditionally,
    that single permitted edit would fail on a field the TA did not touch and cannot fix - so the
    rule is enforced only when the request actually changes the window or the duration.
    """

    @pytest.fixture
    def bad_batch(self, ta_user, make_batch):
        return make_batch(
            ta_user,
            status=Batch.Status.IN_PROGRESS,
            link_valid_until=timezone.now() + timedelta(minutes=26),
            exam_duration_minutes=45,
        )

    def test_editing_a_cutoff_on_a_legacy_bad_batch_still_works(self, bad_batch):
        serializer = BatchSerializer(bad_batch, data={'logical_cutoff': 60}, partial=True)
        assert serializer.is_valid(), serializer.errors

    def test_but_the_window_cannot_be_made_worse(self, bad_batch):
        serializer = BatchSerializer(
            bad_batch,
            data={'link_valid_until': bad_batch.link_valid_from + timedelta(minutes=5)},
            partial=True,
        )
        assert not serializer.is_valid()

    def test_and_fixing_the_window_properly_is_accepted(self, bad_batch):
        serializer = BatchSerializer(
            bad_batch,
            data={'link_valid_until': bad_batch.link_valid_from + timedelta(hours=3)},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
