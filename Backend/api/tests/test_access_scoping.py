"""Who can see what.

Both rules here have been reversed during development - batches twice - so they are worth
pinning down explicitly:

  batches    - every live batch, for admins and Staffing Users alike
  candidates - visible to every admin/TA regardless of who uploaded them

A regression in either direction is silent: too narrow and staff quietly lose sight of records
they need, too wide and a scoping requirement is gone with nothing failing.

The sharing is about WHICH BATCHES, not about which controls. The admin-only controls below
are gated on the role rather than on ownership, so widening visibility must not have widened
them - TestSharingDidNotMakeEveryoneAnAdmin is what would notice if it had.
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


class TestEveryStaffUserReachesEveryBatch:
    def test_ta_can_access_their_own_batch(self, ta_user, make_batch):
        assert can_access_batch(ta_user, make_batch(ta_user)) is True

    def test_ta_can_access_another_tas_batch(self, ta_user, other_ta_user, make_batch):
        """The point of the change: covering a colleague's drive needs no administrator."""
        assert can_access_batch(ta_user, make_batch(other_ta_user)) is True

    def test_admin_can_access_any_batch(self, admin_user, other_ta_user, make_batch):
        assert can_access_batch(admin_user, make_batch(other_ta_user)) is True

    def test_a_candidates_attempt_is_not_staff(self, make_batch, ta_user):
        """can_access_batch is reached with request.user set to an ExamAttempt on the exam
        endpoints, which has no `role` at all. It must refuse, not raise.
        """
        class _Attempt:
            pass

        assert can_access_batch(_Attempt(), make_batch(ta_user)) is False

    def test_ta_queryset_contains_every_batch(self, ta_user, other_ta_user, make_batch):
        own = make_batch(ta_user)
        foreign = make_batch(other_ta_user)

        ids = set(visible_batches_qs(ta_user).values_list('batch_id', flat=True))
        assert {own.batch_id, foreign.batch_id} <= ids

    def test_admin_and_ta_see_the_same_batches(self, admin_user, ta_user, other_ta_user,
                                               make_batch):
        make_batch(ta_user)
        make_batch(other_ta_user)

        assert (set(visible_batches_qs(ta_user).values_list('batch_id', flat=True))
                == set(visible_batches_qs(admin_user).values_list('batch_id', flat=True)))

    def test_a_deleted_batch_is_still_hidden_from_everyone(self, ta_user, make_batch):
        """Sharing widened WHO sees a batch, not WHICH batches exist."""
        batch = make_batch(ta_user)
        batch.is_deleted = True
        batch.save(update_fields=['is_deleted'])

        assert batch.batch_id not in set(
            visible_batches_qs(ta_user).values_list('batch_id', flat=True))


class TestBatchScopingOverHttp:
    def test_foreign_batch_detail_opens(self, ta_user, other_ta_user, client_for, make_batch):
        foreign = make_batch(other_ta_user)
        response = client_for(ta_user).get('/api/batches/%d/' % foreign.batch_id)
        assert response.status_code == 200

    def test_foreign_batch_is_in_the_list(self, ta_user, other_ta_user, client_for, make_batch):
        own = make_batch(ta_user)
        foreign = make_batch(other_ta_user)

        response = client_for(ta_user).get('/api/batches/?status=all&page_size=200')
        ids = [row['batch_id'] for row in response.data['results']]

        assert {own.batch_id, foreign.batch_id} <= set(ids)

    def test_a_batch_that_does_not_exist_is_still_404(self, ta_user, client_for):
        """Sharing must not have turned a missing batch into a server error."""
        assert client_for(ta_user).get('/api/batches/99999999/').status_code == 404

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


class TestSharingDidNotMakeEveryoneAnAdmin:
    """Sharing batches widened WHICH BATCHES a Staffing User reaches, not WHICH CONTROLS.

    These gates are on the role, not on ownership, so widening visibility should have left them
    exactly where they were. They are asserted against a TA's OWN batch deliberately: if one of
    them ever starts reading ownership instead of role, shared access would silently hand every
    Staffing User a control that grades results or reconfigures every future batch.
    """

    def test_a_ta_cannot_change_cutoffs_on_their_own_batch(self, ta_user, client_for,
                                                           make_batch):
        batch = make_batch(ta_user)
        response = client_for(ta_user).patch(
            '/api/batches/%d/' % batch.batch_id,
            {'section_cutoffs': [{'section_id': 1, 'cutoff_marks': 5}]},
            format='json',
        )
        assert response.status_code == 403

    def test_a_ta_cannot_change_cutoffs_on_a_shared_batch(self, ta_user, other_ta_user,
                                                          client_for, make_batch):
        batch = make_batch(other_ta_user)
        response = client_for(ta_user).patch(
            '/api/batches/%d/' % batch.batch_id,
            {'section_cutoffs': [{'section_id': 1, 'cutoff_marks': 5}]},
            format='json',
        )
        assert response.status_code == 403

    def test_a_ta_cannot_reach_the_cutoff_preview(self, ta_user, client_for, make_batch):
        batch = make_batch(ta_user)
        response = client_for(ta_user).post(
            '/api/batches/%d/cutoff-preview/' % batch.batch_id,
            {'section_cutoffs': []}, format='json',
        )
        assert response.status_code == 403

    def test_a_ta_cannot_read_or_change_the_org_default_batch_config(self, ta_user, client_for):
        client = client_for(ta_user)
        assert client.get('/api/batches/defaults/').status_code == 403
        assert client.put('/api/batches/defaults/', {}, format='json').status_code == 403


class TestASharedBatchCanActuallyBeManaged:
    """The other half of the request: not just visible, but workable. Deactivating and
    completing somebody else's batch were both asked for explicitly.
    """

    def test_a_ta_can_edit_a_colleagues_batch(self, ta_user, other_ta_user, client_for,
                                              make_batch):
        # A DRAFT batch: once one is finalized only its cutoffs may change, and that lock is on
        # the batch's STATUS rather than on who owns it - an admin editing their own finalized
        # batch is refused identically. Using a live batch here would assert the status lock
        # and say nothing at all about sharing.
        batch = make_batch(other_ta_user, status=Batch.Status.DRAFT)
        response = client_for(ta_user).patch(
            '/api/batches/%d/' % batch.batch_id,
            {'batch_name': 'Renamed by a colleague'}, format='json',
        )
        assert response.status_code == 200

    def test_a_ta_can_deactivate_a_colleagues_batch(self, ta_user, other_ta_user, client_for,
                                                    make_batch):
        batch = make_batch(other_ta_user)
        response = client_for(ta_user).post(
            '/api/batches/%d/deactivate/' % batch.batch_id, {}, format='json',
        )
        assert response.status_code in (200, 204)
