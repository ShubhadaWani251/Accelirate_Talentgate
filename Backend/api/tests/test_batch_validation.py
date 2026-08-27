"""Batch configuration under the admin-defaults model.

The exam schedule, question counts and cutoffs used to be entered per-batch at creation. Now
they're an org-wide default (services/batch_defaults.py, admin-only) snapshotted onto each batch
at creation time; only the assessment link window is still set per-batch, and only later - on
the wizard's "Review & Send Invite" step, not at creation. This file covers: the snapshot itself,
that duration/question-count fields are truly locked afterward (not just hidden), that cutoffs
stay editable per-batch without leaking into the shared defaults, and the link-window-vs-duration
rule, which now has to hold even though creation no longer supplies either side of it.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from api.models import Batch
from api.serializers.batch import BatchSerializer, link_window_error
from api.services.batch_defaults import get_batch_defaults, save_batch_defaults


class TestCreationSnapshotsDefaults:
    def test_only_name_and_college_are_needed(self, ta_user, client_for):
        response = client_for(ta_user).post(
            '/api/batches/', {'batch_name': 'New Batch', 'college_name': 'Test College'},
            format='json',
        )
        assert response.status_code == 201, response.data

    def test_the_new_batch_has_no_link_window_yet(self, ta_user, client_for):
        response = client_for(ta_user).post(
            '/api/batches/', {'batch_name': 'New Batch', 'college_name': 'Test College'},
            format='json',
        )
        assert response.data['link_valid_from'] is None
        assert response.data['link_valid_until'] is None

    def test_exam_config_matches_the_current_admin_defaults(self, ta_user, client_for):
        save_batch_defaults({
            'exam_duration_minutes': 33,
            'logical_questions': 4, 'quantitative_questions': 5,
            'verbal_questions': 6, 'programming_questions': 7,
            'logical_cutoff': 55, 'quantitative_cutoff': 60,
            'verbal_cutoff': 65, 'programming_cutoff': 70,
        }, ta_user)

        response = client_for(ta_user).post(
            '/api/batches/', {'batch_name': 'New Batch', 'college_name': 'Test College'},
            format='json',
        )

        assert response.data['exam_duration_minutes'] == 33
        assert response.data['logical_questions'] == 4
        assert response.data['programming_questions'] == 7
        assert float(response.data['verbal_cutoff']) == 65.0

    def test_a_client_supplied_duration_or_count_is_ignored(self, ta_user, client_for):
        """The fields are read-only - not merely defaulted. A request that also supplies its own
        values must not get them; the org-wide default always wins.
        """
        response = client_for(ta_user).post(
            '/api/batches/',
            {
                'batch_name': 'New Batch', 'college_name': 'Test College',
                'exam_duration_minutes': 9999, 'logical_questions': 9999,
            },
            format='json',
        )
        defaults = get_batch_defaults()
        assert response.data['exam_duration_minutes'] == defaults['exam_duration_minutes']
        assert response.data['logical_questions'] == defaults['logical_questions']

    def test_a_client_supplied_cutoff_at_creation_is_also_ignored(self, ta_user, client_for):
        """Cutoffs stay writable later (the post-finalize edit), but not at creation - a fresh
        batch's cutoffs come from the same admin defaults as everything else, not the request.
        """
        response = client_for(ta_user).post(
            '/api/batches/',
            {'batch_name': 'New Batch', 'college_name': 'Test College', 'logical_cutoff': 1},
            format='json',
        )
        defaults = get_batch_defaults()
        assert float(response.data['logical_cutoff']) == defaults['logical_cutoff']

    def test_changing_defaults_afterward_does_not_touch_an_existing_batch(
        self, ta_user, client_for
    ):
        """The whole point of a snapshot: an admin revising the defaults next week must not
        silently reconfigure an exam that candidates may already be sitting.
        """
        created = client_for(ta_user).post(
            '/api/batches/', {'batch_name': 'New Batch', 'college_name': 'Test College'},
            format='json',
        ).data
        original_duration = created['exam_duration_minutes']

        save_batch_defaults({
            'exam_duration_minutes': original_duration + 100,
            'logical_questions': 1, 'quantitative_questions': 1,
            'verbal_questions': 1, 'programming_questions': 1,
            'logical_cutoff': 1, 'quantitative_cutoff': 1,
            'verbal_cutoff': 1, 'programming_cutoff': 1,
        }, ta_user)

        refetched = client_for(ta_user).get('/api/batches/%d/' % created['batch_id']).data
        assert refetched['exam_duration_minutes'] == original_duration


class TestDurationAndCountsAreLockedAfterCreationToo:
    """Not just excluded from the create payload - genuinely un-settable afterward, by anyone,
    at any batch status. A PATCH naming one of these fields is silently ignored (DRF's normal
    behaviour for a read-only field), not rejected - there is no error because there is no
    longer a legitimate way to ask for this at all.
    """

    def test_patching_duration_on_a_draft_has_no_effect(self, ta_user, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, exam_duration_minutes=45)
        serializer = BatchSerializer(batch, data={'exam_duration_minutes': 999}, partial=True)
        assert serializer.is_valid(), serializer.errors
        serializer.save()
        batch.refresh_from_db()
        assert batch.exam_duration_minutes == 45

    def test_patching_a_question_count_has_no_effect(self, ta_user, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, logical_questions=10)
        serializer = BatchSerializer(batch, data={'logical_questions': 999}, partial=True)
        assert serializer.is_valid(), serializer.errors
        serializer.save()
        batch.refresh_from_db()
        assert batch.logical_questions == 10

    def test_over_http_too(self, ta_user, client_for, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, exam_duration_minutes=45)
        response = client_for(ta_user).patch(
            '/api/batches/%d/' % batch.batch_id, {'exam_duration_minutes': 999}, format='json',
        )
        assert response.status_code == 200
        assert response.data['exam_duration_minutes'] == 45


class TestCutoffEditIsIsolatedToOneBatch:
    """The one thing that IS still editable per-batch after creation - and it must never leak
    into the org-wide defaults, or editing one batch's cutoff because its cohort scored
    differently would silently reconfigure every batch created afterward too.
    """

    def test_patching_one_batchs_cutoff_does_not_change_the_defaults(
        self, admin_user, ta_user, client_for, make_batch
    ):
        save_batch_defaults({
            'exam_duration_minutes': 45,
            'logical_questions': 10, 'quantitative_questions': 10,
            'verbal_questions': 10, 'programming_questions': 10,
            'logical_cutoff': 70, 'quantitative_cutoff': 70,
            'verbal_cutoff': 70, 'programming_cutoff': 70,
        }, admin_user)
        batch = make_batch(ta_user, status=Batch.Status.IN_PROGRESS, logical_cutoff=70)

        response = client_for(admin_user).patch(
            '/api/batches/%d/' % batch.batch_id, {'logical_cutoff': 40}, format='json',
        )

        assert response.status_code == 200
        assert float(response.data['logical_cutoff']) == 40.0
        assert get_batch_defaults()['logical_cutoff'] == 70.0

    def test_a_second_batch_is_unaffected_by_the_first_batchs_cutoff_edit(
        self, admin_user, ta_user, client_for, make_batch
    ):
        batch_a = make_batch(ta_user, status=Batch.Status.IN_PROGRESS, logical_cutoff=70)
        batch_b = make_batch(ta_user, status=Batch.Status.IN_PROGRESS, logical_cutoff=70)

        client_for(admin_user).patch(
            '/api/batches/%d/' % batch_a.batch_id, {'logical_cutoff': 40}, format='json',
        )

        batch_b.refresh_from_db()
        assert float(batch_b.logical_cutoff) == 70.0

    def test_a_ta_cannot_change_a_cutoff(self, ta_user, client_for, make_batch):
        batch = make_batch(ta_user, status=Batch.Status.IN_PROGRESS, logical_cutoff=70)

        response = client_for(ta_user).patch(
            '/api/batches/%d/' % batch.batch_id, {'logical_cutoff': 40}, format='json',
        )

        assert response.status_code == 403
        batch.refresh_from_db()
        assert float(batch.logical_cutoff) == 70.0


class TestDefaultsAreAdminOnly:
    def test_a_ta_cannot_read_the_defaults(self, ta_user, client_for):
        assert client_for(ta_user).get('/api/batches/defaults/').status_code == 403

    def test_a_ta_cannot_write_the_defaults(self, ta_user, client_for):
        response = client_for(ta_user).put('/api/batches/defaults/', {
            'exam_duration_minutes': 1,
            'logical_questions': 1, 'quantitative_questions': 1,
            'verbal_questions': 1, 'programming_questions': 1,
            'logical_cutoff': 1, 'quantitative_cutoff': 1,
            'verbal_cutoff': 1, 'programming_cutoff': 1,
        }, format='json')
        assert response.status_code == 403

    def test_an_admin_can_read_and_write_the_defaults(self, admin_user, client_for):
        client = client_for(admin_user)
        assert client.get('/api/batches/defaults/').status_code == 200
        response = client.put('/api/batches/defaults/', {
            'exam_duration_minutes': 50,
            'logical_questions': 8, 'quantitative_questions': 8,
            'verbal_questions': 8, 'programming_questions': 8,
            'logical_cutoff': 65, 'quantitative_cutoff': 65,
            'verbal_cutoff': 65, 'programming_cutoff': 65,
        }, format='json')
        assert response.status_code == 200
        assert response.data['exam_duration_minutes'] == 50


class TestLinkWindowMustCoverTheExam:
    """The rule itself, at the serializer level - unchanged in substance, just now reached only
    through a PATCH (the wizard's "Review & Send Invite" step), since creation never supplies a
    window at all any more.
    """

    def _draft(self, ta_user, make_batch, duration=45):
        return make_batch(ta_user, status=Batch.Status.DRAFT, exam_duration_minutes=duration,
                          link_valid_from=None, link_valid_until=None)

    def test_a_window_shorter_than_the_exam_is_rejected(self, ta_user, make_batch):
        """The real case this came from: a 26-minute window on a 45-minute exam."""
        batch = self._draft(ta_user, make_batch, duration=45)
        start = timezone.now() + timedelta(days=1)
        serializer = BatchSerializer(batch, data={
            'link_valid_from': start, 'link_valid_until': start + timedelta(minutes=26),
        }, partial=True)
        assert not serializer.is_valid()
        assert 'link_valid_until' in serializer.errors

    def test_the_error_names_both_numbers(self, ta_user, make_batch):
        """So whoever is setting the window can see what to change, not just that it's wrong."""
        batch = self._draft(ta_user, make_batch, duration=45)
        start = timezone.now() + timedelta(days=1)
        serializer = BatchSerializer(batch, data={
            'link_valid_from': start, 'link_valid_until': start + timedelta(minutes=26),
        }, partial=True)
        serializer.is_valid()
        message = str(serializer.errors['link_valid_until'][0])
        assert '26' in message
        assert '45' in message

    def test_a_window_exactly_the_exam_length_is_allowed(self, ta_user, make_batch):
        """The boundary is inclusive: equal is sufficient, since the exam clock runs from
        started_at and is not truncated by link expiry.
        """
        batch = self._draft(ta_user, make_batch, duration=45)
        start = timezone.now() + timedelta(days=1)
        serializer = BatchSerializer(batch, data={
            'link_valid_from': start, 'link_valid_until': start + timedelta(minutes=45),
        }, partial=True)
        assert serializer.is_valid(), serializer.errors

    def test_a_longer_window_is_allowed(self, ta_user, make_batch):
        batch = self._draft(ta_user, make_batch, duration=45)
        start = timezone.now() + timedelta(days=1)
        serializer = BatchSerializer(batch, data={
            'link_valid_from': start, 'link_valid_until': start + timedelta(days=7),
        }, partial=True)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.parametrize('window,duration', [(1, 2), (44, 45), (0, 1)])
    def test_every_short_window_is_caught(self, ta_user, make_batch, window, duration):
        batch = self._draft(ta_user, make_batch, duration=duration)
        start = timezone.now() + timedelta(days=1)
        serializer = BatchSerializer(batch, data={
            'link_valid_from': start, 'link_valid_until': start + timedelta(minutes=window),
        }, partial=True)
        assert not serializer.is_valid()

    def test_end_before_start_is_still_rejected_first(self, ta_user, make_batch):
        """The pre-existing check must keep its own clearer message rather than being replaced
        by the duration one.
        """
        batch = self._draft(ta_user, make_batch, duration=45)
        start = timezone.now() + timedelta(days=1)
        serializer = BatchSerializer(batch, data={
            'link_valid_from': start, 'link_valid_until': start - timedelta(minutes=10),
        }, partial=True)
        assert not serializer.is_valid()
        assert 'Must be after Link Valid From.' in str(serializer.errors['link_valid_until'][0])

    def test_setting_the_window_for_the_first_time_is_the_normal_case(self, ta_user, make_batch):
        """This is the ordinary path now, not an edge case: every batch's window starts null and
        is set exactly once, on the Review & Send Invite step.
        """
        batch = self._draft(ta_user, make_batch, duration=45)
        assert batch.link_valid_from is None
        start = timezone.now() + timedelta(days=1)
        serializer = BatchSerializer(batch, data={
            'link_valid_from': start, 'link_valid_until': start + timedelta(hours=2),
        }, partial=True)
        assert serializer.is_valid(), serializer.errors
        saved = serializer.save()
        assert saved.link_valid_from is not None

    def test_an_unrelated_edit_is_not_blocked(self, ta_user, make_batch):
        batch = self._draft(ta_user, make_batch, duration=45)
        serializer = BatchSerializer(batch, data={'batch_name': 'Renamed'}, partial=True)
        assert serializer.is_valid(), serializer.errors


class TestLinkWindowErrorHelper:
    """The extracted function both BatchSerializer.validate and BatchFinalizeView call - tested
    directly so its "missing input -> None" contract (deliberately permissive; callers decide
    whether unset is acceptable at their point in the flow) doesn't get lost in either caller's
    test coverage.
    """

    def test_none_when_anything_is_missing(self):
        now = timezone.now()
        assert link_window_error(None, now, 45) is None
        assert link_window_error(now, None, 45) is None
        assert link_window_error(now, now + timedelta(hours=1), None) is None

    def test_none_when_the_window_covers_the_exam(self):
        start = timezone.now()
        assert link_window_error(start, start + timedelta(minutes=45), 45) is None

    def test_a_message_when_it_does_not(self):
        start = timezone.now()
        error = link_window_error(start, start + timedelta(minutes=26), 45)
        assert error is not None
        assert '26' in error and '45' in error


class TestFinalizeRequiresAValidWindow:
    """BatchFinalizeView is the last point before invites can go out, and has to hold even if a
    caller skipped the PATCH that normally sets the window - it must not trust an earlier step.
    """

    def _ready_to_finalize(self, ta_user, make_batch, make_candidate, **batch_overrides):
        from api.models import Candidate
        batch = make_batch(ta_user, status=Batch.Status.DRAFT, **batch_overrides)
        candidate = make_candidate(batch, ta_user, validation_status=Candidate.ValidationStatus.OK)
        return batch, candidate

    def test_finalize_is_refused_with_no_window_set(
        self, ta_user, client_for, make_batch, make_candidate
    ):
        batch, candidate = self._ready_to_finalize(
            ta_user, make_batch, make_candidate,
            link_valid_from=None, link_valid_until=None,
        )
        response = client_for(ta_user).post(
            '/api/batches/%d/finalize/' % batch.batch_id,
            {'candidate_ids': [candidate.candidate_id]}, format='json',
        )
        assert response.status_code == 400
        assert 'valid-from' in response.data['detail'] or 'window' in response.data['detail']
        batch.refresh_from_db()
        assert batch.status == Batch.Status.DRAFT

    def test_finalize_is_refused_when_the_window_is_too_short(
        self, ta_user, client_for, make_batch, make_candidate
    ):
        start = timezone.now() + timedelta(days=1)
        batch, candidate = self._ready_to_finalize(
            ta_user, make_batch, make_candidate,
            exam_duration_minutes=45,
            link_valid_from=start, link_valid_until=start + timedelta(minutes=10),
        )
        response = client_for(ta_user).post(
            '/api/batches/%d/finalize/' % batch.batch_id,
            {'candidate_ids': [candidate.candidate_id]}, format='json',
        )
        assert response.status_code == 400
        batch.refresh_from_db()
        assert batch.status == Batch.Status.DRAFT

    def test_finalize_succeeds_once_the_window_is_set_properly(
        self, ta_user, client_for, make_batch, make_candidate
    ):
        start = timezone.now() + timedelta(days=1)
        batch, candidate = self._ready_to_finalize(
            ta_user, make_batch, make_candidate,
            exam_duration_minutes=45,
            link_valid_from=start, link_valid_until=start + timedelta(hours=2),
        )
        response = client_for(ta_user).post(
            '/api/batches/%d/finalize/' % batch.batch_id,
            {'candidate_ids': [candidate.candidate_id]}, format='json',
        )
        assert response.status_code == 200, response.data
        batch.refresh_from_db()
        assert batch.status == Batch.Status.IN_PROGRESS


class TestFullFlowEndToEnd:
    """Walks the exact sequence the new wizard actually performs, entirely over HTTP: create
    with just a name and college, patch in the link window on what is now the last step, then
    finalize and send. Each piece above is tested in isolation; this is the one place that
    proves they still fit together as a single pipeline.
    """

    def test_create_then_set_window_then_finalize_then_invite(
        self, ta_user, client_for, make_candidate
    ):
        client = client_for(ta_user)

        created = client.post(
            '/api/batches/', {'batch_name': 'E2E Batch', 'college_name': 'Test College'},
            format='json',
        )
        assert created.status_code == 201, created.data
        batch_id = created.data['batch_id']
        assert created.data['link_valid_from'] is None

        from api.models import Batch, Candidate
        batch = Batch.objects.get(pk=batch_id)
        candidate = make_candidate(batch, ta_user, validation_status=Candidate.ValidationStatus.OK,
                                   status=Candidate.Status.PENDING_INVITE)

        start = timezone.now() + timedelta(days=1)
        duration = created.data['exam_duration_minutes']
        patched = client.patch(
            '/api/batches/%d/' % batch_id,
            {
                'link_valid_from': start.isoformat(),
                'link_valid_until': (start + timedelta(minutes=duration + 30)).isoformat(),
            },
            format='json',
        )
        assert patched.status_code == 200, patched.data

        finalized = client.post(
            '/api/batches/%d/finalize/' % batch_id,
            {'candidate_ids': [candidate.candidate_id]}, format='json',
        )
        assert finalized.status_code == 200, finalized.data

        sent = client.post(
            '/api/batches/%d/send-invites/' % batch_id,
            {'candidate_ids': [candidate.candidate_id]}, format='json',
        )
        assert sent.status_code == 200, sent.data

        from api.models import Invitation
        assert Invitation.objects.filter(batch_id=batch_id, candidate=candidate).exists()
        batch.refresh_from_db()
        assert batch.status == Batch.Status.IN_PROGRESS

    def test_finalizing_before_the_window_is_set_is_refused_in_the_same_flow(
        self, ta_user, client_for, make_candidate
    ):
        """The gate that exists in case the frontend's own PATCH step is ever skipped or
        reordered - finalize must not trust that an earlier step ran.
        """
        client = client_for(ta_user)
        created = client.post(
            '/api/batches/', {'batch_name': 'E2E Batch 2', 'college_name': 'Test College'},
            format='json',
        )
        from api.models import Batch, Candidate
        batch = Batch.objects.get(pk=created.data['batch_id'])
        candidate = make_candidate(batch, ta_user, validation_status=Candidate.ValidationStatus.OK)

        finalized = client.post(
            '/api/batches/%d/finalize/' % batch.batch_id,
            {'candidate_ids': [candidate.candidate_id]}, format='json',
        )
        assert finalized.status_code == 400


class TestExistingBadDataIsGrandfathered:
    """One live batch predates the link-window validation with a 26-minute window on a
    45-minute exam. Its status permits only the section cutoffs to be edited. If the check ran
    unconditionally, that single permitted edit would fail on a field nobody touched and cannot
    fix - so the rule is enforced only when the request actually changes the window.
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
