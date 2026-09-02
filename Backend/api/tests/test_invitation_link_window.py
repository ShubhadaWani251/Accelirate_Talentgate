"""A re-invite can be given its own valid-from/until window, independent of the batch's.

Reported live: resending a candidate on an already-finalized batch with a new window failed
with "This batch has been finalized - only the section cutoffs can still be changed" - the
first implementation tried to PATCH the batch's own link_valid_from/until, which
views/batches.py's BatchDetailView.EDITABLE_AFTER_DRAFT deliberately locks once a batch leaves
Draft (changing it would move the window for every OTHER candidate in the batch too). The fix
gives the INVITATION its own link_valid_from (link_expired_at already worked this way), read by
services/exam_session.invitation_opens_at/link_not_yet_open in preference to the batch's.
"""

from datetime import timedelta

from django.utils import timezone

from api.models import Batch, Invitation
from api.services import exam_session
from api.services.invites import create_single_reinvite


class TestCreateSingleReinviteWithoutOverride:
    def test_link_valid_from_stays_null_and_expiry_comes_from_the_batch(
        self, ta_user, make_batch, make_candidate,
    ):
        """Regression: identical to the behaviour before these parameters existed."""
        now = timezone.now()
        batch = make_batch(
            ta_user, status=Batch.Status.IN_PROGRESS,
            link_valid_from=now, link_valid_until=now + timedelta(days=2),
        )
        candidate = make_candidate(batch, ta_user)

        invitation = create_single_reinvite(candidate, ta_user)

        assert invitation.link_valid_from is None
        assert invitation.link_expired_at == batch.link_valid_until


class TestCreateSingleReinviteWithOverride:
    def test_stores_its_own_window_independent_of_the_batch(
        self, ta_user, make_batch, make_candidate,
    ):
        now = timezone.now()
        batch = make_batch(
            ta_user, status=Batch.Status.IN_PROGRESS,
            link_valid_from=now, link_valid_until=now + timedelta(days=2),
        )
        candidate = make_candidate(batch, ta_user)
        new_from = now + timedelta(days=5)
        new_until = now + timedelta(days=6)

        invitation = create_single_reinvite(candidate, ta_user, new_from, new_until)

        assert invitation.link_valid_from == new_from
        assert invitation.link_expired_at == new_until
        # The batch's own window is untouched - this was the actual bug.
        batch.refresh_from_db()
        assert batch.link_valid_from == now
        assert batch.link_valid_until == now + timedelta(days=2)


class TestExamSessionPrefersTheInvitationsOwnWindow:
    def test_invitation_opens_at_falls_back_to_the_batch_when_unset(
        self, ta_user, make_batch, make_candidate, make_invitation,
    ):
        now = timezone.now()
        batch = make_batch(ta_user, link_valid_from=now, link_valid_until=now + timedelta(days=2))
        candidate = make_candidate(batch, ta_user)
        invitation = make_invitation(candidate, ta_user, link_expired_at=now + timedelta(days=2))

        assert exam_session.invitation_opens_at(invitation) == now

    def test_a_re_invites_own_window_overrides_the_batchs(
        self, ta_user, make_batch, make_candidate, make_invitation,
    ):
        now = timezone.now()
        # Batch's own window already open...
        batch = make_batch(
            ta_user, link_valid_from=now - timedelta(days=1),
            link_valid_until=now + timedelta(days=10),
        )
        candidate = make_candidate(batch, ta_user)
        # ...but THIS invitation's own window has not opened yet.
        own_open = now + timedelta(days=1)
        invitation = make_invitation(
            candidate, ta_user, link_valid_from=own_open,
            link_expired_at=now + timedelta(days=2),
        )

        assert exam_session.invitation_opens_at(invitation) == own_open
        assert exam_session.link_not_yet_open(invitation) is True

    def test_begin_exam_blocks_on_the_invitations_own_window_not_the_batchs(
        self, ta_user, make_batch, make_candidate, make_invitation,
    ):
        now = timezone.now()
        batch = make_batch(
            ta_user, link_valid_from=now - timedelta(days=1),
            link_valid_until=now + timedelta(days=10),
            logical_questions=0, quantitative_questions=0,
            verbal_questions=0, programming_questions=0,
        )
        candidate = make_candidate(batch, ta_user)
        invitation = make_invitation(
            candidate, ta_user, link_valid_from=now + timedelta(days=1),
            link_expired_at=now + timedelta(days=2),
        )

        attempt, _ = exam_session.start_or_resume_attempt(invitation.pk, '127.0.0.1', 'pytest')
        with __import__('pytest').raises(exam_session.ExamNotYetOpenError) as exc_info:
            exam_session.begin_exam(attempt)
        assert exc_info.value.opens_at == invitation.link_valid_from


class TestResendEndpointAcceptsAPerInvitationWindow:
    def test_resend_on_an_already_finalized_batch_succeeds_and_leaves_the_batch_untouched(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        """The exact reported bug."""
        now = timezone.now()
        batch = make_batch(
            ta_user, status=Batch.Status.IN_PROGRESS,
            link_valid_from=now, link_valid_until=now + timedelta(days=2),
            exam_duration_minutes=45,
        )
        candidate = make_candidate(batch, ta_user)
        new_from = now + timedelta(days=3)
        new_until = now + timedelta(days=3, hours=2)

        response = client_for(ta_user).post(
            '/api/candidates/%d/resend-invite/' % candidate.candidate_id,
            {'link_valid_from': new_from.isoformat(), 'link_valid_until': new_until.isoformat()},
            format='json',
        )

        assert response.status_code == 200, response.data
        batch.refresh_from_db()
        assert batch.link_valid_from == now
        assert batch.link_valid_until == now + timedelta(days=2)
        invitation = Invitation.objects.get(candidate=candidate)
        assert invitation.link_valid_from == new_from
        assert invitation.link_expired_at == new_until

    def test_a_window_shorter_than_the_exam_is_rejected(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        now = timezone.now()
        batch = make_batch(
            ta_user, status=Batch.Status.IN_PROGRESS,
            link_valid_from=now, link_valid_until=now + timedelta(days=2),
            exam_duration_minutes=45,
        )
        candidate = make_candidate(batch, ta_user)

        response = client_for(ta_user).post(
            '/api/candidates/%d/resend-invite/' % candidate.candidate_id,
            {'link_valid_from': now.isoformat(),
             'link_valid_until': (now + timedelta(minutes=10)).isoformat()},
            format='json',
        )

        assert response.status_code == 400
        assert not Invitation.objects.filter(candidate=candidate).exists()

    def test_until_before_from_is_rejected(self, ta_user, client_for, make_batch, make_candidate):
        now = timezone.now()
        batch = make_batch(ta_user, status=Batch.Status.IN_PROGRESS)
        candidate = make_candidate(batch, ta_user)

        response = client_for(ta_user).post(
            '/api/candidates/%d/resend-invite/' % candidate.candidate_id,
            {'link_valid_from': now.isoformat(),
             'link_valid_until': (now - timedelta(hours=1)).isoformat()},
            format='json',
        )

        assert response.status_code == 400

    def test_omitting_the_window_still_works_and_inherits_the_batch(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        batch = make_batch(ta_user, status=Batch.Status.IN_PROGRESS)
        candidate = make_candidate(batch, ta_user)

        response = client_for(ta_user).post(
            '/api/candidates/%d/resend-invite/' % candidate.candidate_id, {}, format='json',
        )

        assert response.status_code == 200, response.data
        invitation = Invitation.objects.get(candidate=candidate)
        assert invitation.link_valid_from is None
        assert invitation.link_expired_at == batch.link_valid_until


class TestBulkResendEndpointAcceptsASharedWindow:
    def test_applies_the_same_window_to_every_selected_candidate(
        self, ta_user, client_for, make_batch, make_candidate,
    ):
        now = timezone.now()
        batch = make_batch(
            ta_user, status=Batch.Status.IN_PROGRESS,
            exam_duration_minutes=45,
        )
        c1 = make_candidate(batch, ta_user, email='c1@example.test')
        c2 = make_candidate(batch, ta_user, email='c2@example.test')
        new_from = now + timedelta(days=1)
        new_until = now + timedelta(days=1, hours=2)

        response = client_for(ta_user).post(
            '/api/candidates/resend-invite/',
            {'candidate_ids': [c1.candidate_id, c2.candidate_id],
             'link_valid_from': new_from.isoformat(), 'link_valid_until': new_until.isoformat()},
            format='json',
        )

        assert response.status_code == 200, response.data
        assert response.data['sent_count'] == 2
        for c in (c1, c2):
            invitation = Invitation.objects.get(candidate=c)
            assert invitation.link_valid_from == new_from
            assert invitation.link_expired_at == new_until

    def test_skips_only_candidates_whose_own_batch_duration_does_not_fit(
        self, ta_user, make_batch, make_candidate, client_for,
    ):
        now = timezone.now()
        short_window_ok_batch = make_batch(
            ta_user, status=Batch.Status.IN_PROGRESS, exam_duration_minutes=30,
        )
        long_exam_batch = make_batch(
            ta_user, status=Batch.Status.IN_PROGRESS, exam_duration_minutes=120,
        )
        fits = make_candidate(short_window_ok_batch, ta_user, email='fits@example.test')
        too_short = make_candidate(long_exam_batch, ta_user, email='tooshort@example.test')
        new_from = now + timedelta(days=1)
        new_until = new_from + timedelta(minutes=45)  # covers 30 min, not 120 min

        response = client_for(ta_user).post(
            '/api/candidates/resend-invite/',
            {'candidate_ids': [fits.candidate_id, too_short.candidate_id],
             'link_valid_from': new_from.isoformat(), 'link_valid_until': new_until.isoformat()},
            format='json',
        )

        assert response.status_code == 200, response.data
        assert response.data['sent_count'] == 1
        assert Invitation.objects.filter(candidate=fits).exists()
        assert not Invitation.objects.filter(candidate=too_short).exists()
