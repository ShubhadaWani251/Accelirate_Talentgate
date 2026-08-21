"""Who can see what.

The two rules here are deliberately asymmetric and have each been reversed once during
development, so they are worth pinning down explicitly:

  batches    - scoped to their creator (an admin sees all). A work queue.
  candidates - visible to every admin/TA regardless of who uploaded them. A directory of people.

A regression in either direction is silent: too narrow and staff quietly lose sight of records
they need, too wide and the scoping requirement is gone with nothing failing.
"""

from api.models import Batch
from api.services.access import (
    can_access_batch, is_admin, visible_batches_qs, visible_candidates_qs,
)


class TestRoleHelper:
    def test_admin_is_admin(self, admin_user):
        assert is_admin(admin_user) is True

    def test_ta_is_not_admin(self, ta_user):
        assert is_admin(ta_user) is False


class TestBatchScoping:
    def test_ta_can_access_their_own_batch(self, ta_user, make_batch):
        assert can_access_batch(ta_user, make_batch(ta_user)) is True

    def test_ta_cannot_access_another_tas_batch(self, ta_user, other_ta_user, make_batch):
        assert can_access_batch(ta_user, make_batch(other_ta_user)) is False

    def test_admin_can_access_any_batch(self, admin_user, other_ta_user, make_batch):
        assert can_access_batch(admin_user, make_batch(other_ta_user)) is True

    def test_ta_queryset_contains_only_their_own(self, ta_user, other_ta_user, make_batch):
        own = make_batch(ta_user)
        foreign = make_batch(other_ta_user)

        ids = set(visible_batches_qs(ta_user).values_list('batch_id', flat=True))
        assert own.batch_id in ids
        assert foreign.batch_id not in ids

    def test_admin_queryset_contains_every_batch(self, admin_user, ta_user, other_ta_user,
                                                 make_batch):
        a = make_batch(ta_user)
        b = make_batch(other_ta_user)

        ids = set(visible_batches_qs(admin_user).values_list('batch_id', flat=True))
        assert {a.batch_id, b.batch_id} <= ids

    def test_scoping_is_on_creator_not_assignee(self, ta_user, other_ta_user, make_batch):
        """created_by is the rule, not primary_ta_user. They are the same at creation, so this
        only diverges if a batch is ever reassigned - and then the creator keeps the view.
        """
        batch = make_batch(ta_user)
        Batch.objects.filter(pk=batch.pk).update(primary_ta_user=other_ta_user)

        assert can_access_batch(ta_user, Batch.objects.get(pk=batch.pk)) is True
        assert can_access_batch(other_ta_user, Batch.objects.get(pk=batch.pk)) is False


class TestBatchScopingOverHttp:
    def test_foreign_batch_detail_returns_404(self, ta_user, other_ta_user, client_for,
                                              make_batch):
        """404 rather than 403 - a 403 would confirm the batch exists."""
        foreign = make_batch(other_ta_user)
        response = client_for(ta_user).get('/api/batches/%d/' % foreign.batch_id)
        assert response.status_code == 404

    def test_foreign_batch_absent_from_list(self, ta_user, other_ta_user, client_for,
                                            make_batch):
        own = make_batch(ta_user)
        foreign = make_batch(other_ta_user)

        response = client_for(ta_user).get('/api/batches/?status=all&page_size=200')
        ids = [row['batch_id'] for row in response.data['results']]

        assert own.batch_id in ids
        assert foreign.batch_id not in ids

    def test_list_and_detail_agree(self, ta_user, other_ta_user, client_for, make_batch):
        """The bug this prevents: a batch counted in a list but 404ing on its own page."""
        make_batch(ta_user)
        make_batch(other_ta_user)
        client = client_for(ta_user)

        listed = [row['batch_id'] for row in
                  client.get('/api/batches/?status=all&page_size=200').data['results']]
        for batch_id in listed:
            assert client.get('/api/batches/%d/' % batch_id).status_code == 200

    def test_admin_sees_the_foreign_batch_over_http(self, admin_user, other_ta_user,
                                                    client_for, make_batch):
        foreign = make_batch(other_ta_user)
        response = client_for(admin_user).get('/api/batches/%d/' % foreign.batch_id)
        assert response.status_code == 200


class TestCandidateVisibilityIsUploaderAgnostic:
    """The deliberate asymmetry with batch scoping above: All Candidates shows everyone."""

    def test_ta_sees_a_candidate_uploaded_by_another_ta(self, ta_user, other_ta_user,
                                                        make_batch, make_candidate):
        foreign = make_candidate(make_batch(other_ta_user), other_ta_user)
        ids = set(visible_candidates_qs(ta_user).values_list('candidate_id', flat=True))
        assert foreign.candidate_id in ids

    def test_visibility_is_the_same_for_admin_and_ta(self, admin_user, ta_user, other_ta_user,
                                                     make_batch, make_candidate):
        make_candidate(make_batch(ta_user), ta_user)
        make_candidate(make_batch(other_ta_user), other_ta_user)

        assert (set(visible_candidates_qs(ta_user).values_list('candidate_id', flat=True))
                == set(visible_candidates_qs(admin_user).values_list('candidate_id', flat=True)))

    def test_foreign_candidate_opens_over_http(self, ta_user, other_ta_user, client_for,
                                               make_batch, make_candidate):
        foreign = make_candidate(make_batch(other_ta_user), other_ta_user)
        client = client_for(ta_user)

        listed = [row['candidate_id'] for row in
                  client.get('/api/candidates/?page_size=200').data['results']]
        assert foreign.candidate_id in listed
        assert client.get('/api/candidates/%d/' % foreign.candidate_id).status_code == 200

    def test_draft_batch_candidates_are_still_excluded(self, ta_user, make_batch,
                                                       make_candidate):
        """Uploader-agnostic is not the same as showing everything: rows staged on a Draft batch
        are an incomplete upload, not yet part of the candidate directory.
        """
        draft_candidate = make_candidate(
            make_batch(ta_user, status=Batch.Status.DRAFT), ta_user)
        live_candidate = make_candidate(make_batch(ta_user), ta_user)

        ids = set(visible_candidates_qs(ta_user).values_list('candidate_id', flat=True))
        assert draft_candidate.candidate_id not in ids
        assert live_candidate.candidate_id in ids
