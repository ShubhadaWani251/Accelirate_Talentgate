"""Draft batches are never auto-deleted, and manual deletion (delete_draft_batch / the DELETE
endpoint built on it) is the only way one goes away.

There used to be a 24-hour auto-expiry sweep here; it was removed on request, so this file now
locks in the opposite property (an old Draft survives untouched) alongside the manual path.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from api.models import Batch
from api.services import draft_expiry


def _hours_ago(n):
    return timezone.now() - timedelta(hours=n)


class TestDraftsDoNotAutoExpire:
    """Regression guard for the removed 24-hour sweep: a Draft, however old, is untouched by
    simply existing or being read.
    """

    def test_an_old_draft_is_still_retrievable(self, ta_user, client_for, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(500))
        response = client_for(ta_user).get('/api/batches/%d/' % batch.batch_id)
        assert response.status_code == 200
        assert Batch.objects.filter(batch_id=batch.batch_id).exists()

    def test_an_old_draft_still_appears_in_the_batch_list(self, ta_user, client_for, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(500))
        response = client_for(ta_user).get('/api/batches/?status=all&page_size=200')
        ids = [row['batch_id'] for row in response.data['results']]
        assert batch.batch_id in ids


class TestManualDraftDeletion:
    """delete_draft_batch and the DELETE /api/batches/<id>/ view built on it - the only way a
    Draft is ever removed.
    """

    def test_deleting_a_fresh_draft_removes_it_and_its_candidates(
        self, ta_user, make_batch, make_candidate
    ):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(1))
        make_candidate(batch, ta_user)
        make_candidate(batch, ta_user)

        result = draft_expiry.delete_draft_batch(batch)

        assert result == {'batch_name': batch.batch_name, 'candidates_removed': 2}
        assert not Batch.objects.filter(batch_id=batch.batch_id).exists()

    def test_an_activated_batch_cannot_be_deleted_this_way(self, ta_user, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.IN_PROGRESS)
        with pytest.raises(ValueError):
            draft_expiry.delete_draft_batch(batch)
        assert Batch.objects.filter(batch_id=batch.batch_id).exists()

    def test_delete_endpoint_removes_a_draft(self, ta_user, client_for, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, created_at=_hours_ago(1))

        response = client_for(ta_user).delete('/api/batches/%d/' % batch.batch_id)

        assert response.status_code == 200
        assert not Batch.objects.filter(batch_id=batch.batch_id).exists()

    def test_delete_endpoint_refuses_a_finalized_batch(self, ta_user, client_for, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.IN_PROGRESS)

        response = client_for(ta_user).delete('/api/batches/%d/' % batch.batch_id)

        assert response.status_code == 400
        assert Batch.objects.filter(batch_id=batch.batch_id).exists()
