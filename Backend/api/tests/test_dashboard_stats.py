"""Dashboard stat cards ("Total Candidates" etc.) count real PEOPLE, not batch appearances.

Reported live: "Total Candidates" was counting raw Candidate rows - one per batch upload of
the same person - while the All Candidates page itself already collapsed to one row per person
(see services/candidate_profile.py). The two now share one seam
(services/access.dedupe_by_profile) so they can't disagree again.
"""

from datetime import date, timedelta

from django.utils import timezone

from api.models import Candidate, ExamAttempt
from api.serializers.dashboard import build_dashboard_summary
from api.services.candidate_profile import link_profile

DOB = date(1999, 5, 20)


class TestTotalCandidatesCountsPeopleNotRows:
    def test_the_same_person_in_two_batches_counts_once(
        self, admin_user, make_batch, make_candidate,
    ):
        first = make_candidate(make_batch(admin_user), admin_user, aadhaar_last4='5678',
                               date_of_birth=DOB, first_name='Asha', last_name='Rao')
        link_profile(first)
        second = make_candidate(make_batch(admin_user), admin_user, aadhaar_last4='5678',
                                date_of_birth=DOB, first_name='Asha', last_name='Rao')
        link_profile(second)

        stats = build_dashboard_summary(admin_user)['stats']

        assert stats['total_candidates'] == 1

    def test_unrelated_people_each_count(self, admin_user, make_batch, make_candidate):
        make_candidate(make_batch(admin_user), admin_user, aadhaar_last4='1111',
                       date_of_birth=date(1998, 1, 1))
        make_candidate(make_batch(admin_user), admin_user, aadhaar_last4='2222',
                       date_of_birth=date(1999, 2, 2))

        stats = build_dashboard_summary(admin_user)['stats']

        assert stats['total_candidates'] == 2

    def test_a_candidate_with_no_profile_still_counts(self, admin_user, make_batch, make_candidate):
        make_candidate(make_batch(admin_user), admin_user, aadhaar_last4='')

        stats = build_dashboard_summary(admin_user)['stats']

        assert stats['total_candidates'] == 1

    def test_completed_and_pass_counts_reflect_the_latest_membership(
        self, admin_user, make_batch, make_candidate, make_invitation,
    ):
        """A person's most recent batch appearance is what counts, matching the same
        "recent entry wins" rule the profile itself follows.

        "Completed" is built from the OLDER row's own latest ExamAttempt (SUBMITTED), not
        Candidate.status - nothing in the real exam-taking flow ever writes that field (see
        serializers/dashboard._build_stats' own comment), so pinning this against it would
        test a state the application can never actually produce.
        """
        older = make_candidate(make_batch(admin_user), admin_user, aadhaar_last4='5678',
                               date_of_birth=DOB, result=Candidate.Result.PASS)
        link_profile(older)
        ExamAttempt.objects.create(
            candidate=older, invitation=make_invitation(older, admin_user),
            status=ExamAttempt.Status.SUBMITTED, submitted_at=timezone.now(),
        )
        newer = make_candidate(make_batch(admin_user), admin_user, aadhaar_last4='5678', date_of_birth=DOB,
                               result=Candidate.Result.PENDING)
        link_profile(newer)

        stats = build_dashboard_summary(admin_user)['stats']

        assert stats['total_candidates'] == 1
        assert stats['completed'] == 0
        assert stats['total_pass'] == 0

    def test_completed_counts_a_candidate_whose_latest_attempt_was_submitted(
        self, admin_user, make_batch, make_candidate, make_invitation,
    ):
        """The bug this whole change fixes: Candidate.status is never written to COMPLETED by
        the real exam-taking flow, so filtering on it left this card stuck at 0 regardless of
        how many candidates had actually finished - reported live on a real dashboard showing
        0 completed with real completed exams on record.
        """
        candidate = make_candidate(make_batch(admin_user), admin_user)
        ExamAttempt.objects.create(
            candidate=candidate, invitation=make_invitation(candidate, admin_user),
            status=ExamAttempt.Status.SUBMITTED, submitted_at=timezone.now(),
        )

        stats = build_dashboard_summary(admin_user)['stats']

        assert stats['completed'] == 1

    def test_completed_does_not_count_an_in_progress_attempt(
        self, admin_user, make_batch, make_candidate, make_invitation,
    ):
        candidate = make_candidate(make_batch(admin_user), admin_user)
        ExamAttempt.objects.create(
            candidate=candidate, invitation=make_invitation(candidate, admin_user),
            status=ExamAttempt.Status.IN_PROGRESS,
        )

        stats = build_dashboard_summary(admin_user)['stats']

        assert stats['completed'] == 0


class TestThisWeekFiguresAreMeasuredNotEstimated:
    """The "+N this week" line beside each counter.

    These exist because the reference design showed a week-on-week trend and nothing in the API
    carried one - so rather than compute something plausible in the frontend, where an invented
    number would sit beside real ones and look identical to them, the figures are derived from
    timestamps here. What they are must therefore be exactly what they claim: a count of what
    arrived in the last seven days, which for a running total is how much higher the number is
    than it was a week ago.
    """

    def test_a_candidate_added_this_week_is_counted(self, admin_user, make_batch, make_candidate):
        batch = make_batch(admin_user)
        make_candidate(batch, admin_user)

        stats = build_dashboard_summary(admin_user)['stats']

        assert stats['total_candidates'] == 1
        assert stats['total_candidates_this_week'] == 1

    def test_a_candidate_added_before_the_window_is_not(
        self, admin_user, make_batch, make_candidate
    ):
        """The one that would pass anyway if the filter did nothing at all."""
        batch = make_batch(admin_user)
        old = make_candidate(batch, admin_user)
        Candidate.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=30))

        stats = build_dashboard_summary(admin_user)['stats']

        assert stats['total_candidates'] == 1, 'the running total still counts them'
        assert stats['total_candidates_this_week'] == 0, 'but not as new this week'

    def test_the_boundary_is_seven_days(self, admin_user, make_batch, make_candidate):
        """Six days ago is inside the window, eight days ago is outside it."""
        batch = make_batch(admin_user)
        inside = make_candidate(batch, admin_user)
        outside = make_candidate(batch, admin_user)
        Candidate.objects.filter(pk=inside.pk).update(
            created_at=timezone.now() - timedelta(days=6))
        Candidate.objects.filter(pk=outside.pk).update(
            created_at=timezone.now() - timedelta(days=8))

        stats = build_dashboard_summary(admin_user)['stats']

        assert stats['total_candidates'] == 2
        assert stats['total_candidates_this_week'] == 1

    def test_completed_this_week_follows_when_the_attempt_was_submitted(
        self, admin_user, make_batch, make_candidate, make_invitation
    ):
        """Not when the candidate was created. A candidate added months ago who sat their exam
        yesterday is new to Completed this week, and that is the number the card reports.
        """
        batch = make_batch(admin_user)
        candidate = make_candidate(batch, admin_user)
        Candidate.objects.filter(pk=candidate.pk).update(
            created_at=timezone.now() - timedelta(days=60))
        invitation = make_invitation(candidate, admin_user)
        ExamAttempt.objects.create(
            invitation=invitation, candidate=candidate,
            status=ExamAttempt.Status.SUBMITTED, submitted_at=timezone.now(),
        )

        stats = build_dashboard_summary(admin_user)['stats']

        assert stats['completed'] == 1
        assert stats['completed_this_week'] == 1
        assert stats['total_candidates_this_week'] == 0, 'the person is not new, the result is'

    def test_every_counter_has_a_this_week_partner(self, admin_user):
        """The frontend reads `${key}_this_week` for each card, so a counter without one would
        silently render no trend line rather than fail.
        """
        stats = build_dashboard_summary(admin_user)['stats']

        for key in ('active_batches', 'total_candidates', 'completed', 'total_pass'):
            assert f'{key}_this_week' in stats, f'{key} has no this-week figure'
