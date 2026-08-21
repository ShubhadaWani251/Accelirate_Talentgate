"""The 24-hour Draft batch expiry rule.

Locks in the properties the rule was specified with, particularly the ones that are easy to
break accidentally: the clock starts at creation and is NOT reset by activity, activation stops
expiry permanently, and deletion takes the staged candidates with it.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from api.models import Batch, Candidate
from api.services import draft_expiry


def _hours_ago(n):
    return timezone.now() - timedelta(hours=n)


class TestExpiryWindow:
    def test_lifetime_is_24_hours(self):
        assert draft_expiry.DRAFT_LIFETIME == timedelta(hours=24)

    def test_expiry_is_measured_from_creation(self, ta_user, make_batch):
        created = _hours_ago(5)
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=created)
        assert draft_expiry.draft_expires_at(batch) == created + timedelta(hours=24)

    def test_fresh_draft_is_not_expired(self, ta_user, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(23))
        assert draft_expiry.is_draft_expired(batch) is False

    def test_draft_older_than_24_hours_is_expired(self, ta_user, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(25))
        assert draft_expiry.is_draft_expired(batch) is True

    @pytest.mark.parametrize('status', [
        Batch.Status.IN_PROGRESS,
        Batch.Status.COMPLETED,
        Batch.Status.CANCELLED,
    ])
    def test_only_drafts_ever_expire(self, ta_user, make_batch, status):
        """Activation is permanent. An activated batch is never swept, however old it is."""
        batch = make_batch(ta_user, status=status, created_at=_hours_ago(500))
        assert draft_expiry.is_draft_expired(batch) is False


class TestTimerDoesNotReset:
    """The specified behaviour: the clock runs from creation and nothing restarts it.

    This is the property most likely to regress, because the natural instinct when touching a
    row is to bump an updated_at and then key expiry off that.
    """

    def test_editing_the_batch_does_not_extend_the_deadline(self, ta_user, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(25))
        deadline_before = draft_expiry.draft_expires_at(batch)

        batch.batch_name = 'Renamed after expiry'
        batch.save(update_fields=['batch_name'])
        batch.refresh_from_db()

        assert draft_expiry.draft_expires_at(batch) == deadline_before
        assert draft_expiry.is_draft_expired(batch) is True

    def test_uploading_candidates_does_not_extend_the_deadline(
        self, ta_user, make_batch, make_candidate
    ):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(25))
        deadline_before = draft_expiry.draft_expires_at(batch)

        make_candidate(batch, ta_user)
        make_candidate(batch, ta_user)
        batch.refresh_from_db()

        assert draft_expiry.draft_expires_at(batch) == deadline_before
        assert draft_expiry.is_draft_expired(batch) is True


class TestQuerysetFiltering:
    def test_expired_drafts_queryset_selects_only_expired_drafts(
        self, ta_user, make_batch
    ):
        expired = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(30))
        fresh = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(1))
        activated = make_batch(ta_user, status=Batch.Status.IN_PROGRESS,
                               created_at=_hours_ago(30))

        ids = set(draft_expiry.expired_drafts_queryset().values_list('batch_id', flat=True))
        assert expired.batch_id in ids
        assert fresh.batch_id not in ids
        assert activated.batch_id not in ids

    def test_exclude_expired_hides_expired_drafts_immediately(self, ta_user, make_batch):
        """Closes the window between a draft expiring and the next scheduled sweep: it must
        disappear from listings the moment it expires, not whenever the job next runs.
        """
        expired = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(30))
        fresh = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(1))

        visible = set(
            draft_expiry.exclude_expired(Batch.objects.all())
            .values_list('batch_id', flat=True)
        )
        assert expired.batch_id not in visible
        assert fresh.batch_id in visible


class TestDeletion:
    def test_deleting_an_expired_draft_removes_its_candidates(
        self, ta_user, make_batch, make_candidate
    ):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(30))
        make_candidate(batch, ta_user)
        make_candidate(batch, ta_user)
        batch_id = batch.batch_id

        result = draft_expiry.delete_expired_draft_batches()

        assert result['batches_deleted'] == 1
        assert result['candidates_deleted'] == 2
        assert not Batch.objects.filter(batch_id=batch_id).exists()
        assert not Candidate.objects.filter(batch_id=batch_id).exists()

    def test_sweep_leaves_fresh_and_activated_batches_alone(
        self, ta_user, make_batch, make_candidate
    ):
        fresh = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(2))
        activated = make_batch(ta_user, status=Batch.Status.IN_PROGRESS,
                               created_at=_hours_ago(300))
        make_candidate(fresh, ta_user)
        make_candidate(activated, ta_user)

        result = draft_expiry.delete_expired_draft_batches()

        assert result['batches_deleted'] == 0
        assert Batch.objects.filter(batch_id=fresh.batch_id).exists()
        assert Batch.objects.filter(batch_id=activated.batch_id).exists()
        assert Candidate.objects.count() == 2

    def test_delete_if_expired_is_a_no_op_on_a_fresh_draft(self, ta_user, make_batch):
        """The lazy path: touching a draft that has NOT expired must not delete it."""
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(1))
        # Returns a bool ("was it deleted"), not a count.
        assert draft_expiry.delete_if_expired(batch) is False
        assert Batch.objects.filter(batch_id=batch.batch_id).exists()

    def test_delete_if_expired_removes_an_expired_draft_on_touch(
        self, ta_user, make_batch, make_candidate
    ):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(30))
        make_candidate(batch, ta_user)

        removed = draft_expiry.delete_if_expired(batch)

        assert removed is True
        assert not Batch.objects.filter(batch_id=batch.batch_id).exists()

    def test_delete_if_expired_never_touches_an_activated_batch(self, ta_user, make_batch):
        """Guards the activation/expiry race: once activated, the sweep must let it be even if
        it was eligible a moment earlier.
        """
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(30))
        Batch.objects.filter(pk=batch.pk).update(status=Batch.Status.IN_PROGRESS)
        batch.refresh_from_db()

        assert draft_expiry.delete_if_expired(batch) is False
        assert Batch.objects.filter(batch_id=batch.batch_id).exists()

    def test_sweep_is_idempotent(self, ta_user, make_batch):
        make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(30))
        first = draft_expiry.delete_expired_draft_batches()
        second = draft_expiry.delete_expired_draft_batches()
        assert first['batches_deleted'] == 1
        assert second['batches_deleted'] == 0


class TestApiRefusesExpiredDrafts:
    def test_an_expired_draft_is_not_retrievable_and_is_deleted_on_the_attempt(
        self, ta_user, client_for, make_batch
    ):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(30))
        response = client_for(ta_user).get('/api/batches/%d/' % batch.batch_id)

        assert response.status_code == 404
        # The lazy layer: asking for it is what removes it.
        assert not Batch.objects.filter(batch_id=batch.batch_id).exists()

    def test_an_expired_draft_is_absent_from_the_batch_list(
        self, ta_user, client_for, make_batch
    ):
        expired = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(30))
        fresh = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(1))

        response = client_for(ta_user).get('/api/batches/?status=all&page_size=200')
        ids = [row['batch_id'] for row in response.data['results']]

        assert response.status_code == 200
        assert expired.batch_id not in ids
        assert fresh.batch_id in ids
