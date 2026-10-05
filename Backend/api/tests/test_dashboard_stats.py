"""Dashboard stat cards ("Total Candidates" etc.) count real PEOPLE, not batch appearances.

Reported live: "Total Candidates" was counting raw Candidate rows - one per batch upload of
the same person - while the All Candidates page itself already collapsed to one row per person
(see services/candidate_profile.py). The two now share one seam
(services/access.dedupe_by_profile) so they can't disagree again.
"""

from datetime import date, timedelta

from django.utils import timezone

from api.models import Batch, Candidate, ExamAttempt
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


class TestStatCardsCoverRunningBatchesOnly:
    """Every stat card describes the work currently running - candidates in an In Progress batch.

    "Active Batches" always meant that. The other three counted all time, so a dashboard could
    report 22 active batches beside 149 candidates most of whom had finished months ago, and the
    row read as four unrelated numbers rather than one picture.

    Each card also links to All Candidates carrying ?batch_status=in_progress, so these counts
    and that list have to agree - the last test here is the one that actually pins that.
    """

    def test_a_candidate_in_a_finished_batch_is_not_counted(
        self, admin_user, make_batch, make_candidate, make_invitation,
    ):
        done = make_batch(admin_user, status=Batch.Status.COMPLETED)
        candidate = make_candidate(done, admin_user, result=Candidate.Result.PASS)
        ExamAttempt.objects.create(
            candidate=candidate, invitation=make_invitation(candidate, admin_user),
            status=ExamAttempt.Status.SUBMITTED, submitted_at=timezone.now(),
        )

        stats = build_dashboard_summary(admin_user)['stats']

        assert stats['total_candidates'] == 0
        assert stats['completed'] == 0
        assert stats['total_pass'] == 0

    def test_draft_and_cancelled_batches_are_not_counted_either(
        self, admin_user, make_batch, make_candidate,
    ):
        make_candidate(make_batch(admin_user, status=Batch.Status.DRAFT), admin_user)
        make_candidate(make_batch(admin_user, status=Batch.Status.CANCELLED), admin_user)

        stats = build_dashboard_summary(admin_user)['stats']

        assert stats['total_candidates'] == 0

    def test_someone_in_both_a_finished_and_a_running_batch_still_counts(
        self, admin_user, make_batch, make_candidate,
    ):
        """The reason the scope is applied BEFORE dedupe_by_profile rather than after.

        Dedupe keeps each person's most recently created batch membership. Deduping first would
        pick the newer, finished row here and then filter it away, dropping someone who is in
        fact sitting in a running batch right now - the exact person this number exists to count.
        """
        running = make_candidate(make_batch(admin_user), admin_user,
                                 aadhaar_last4='5678', date_of_birth=DOB)
        link_profile(running)
        finished = make_candidate(make_batch(admin_user, status=Batch.Status.COMPLETED),
                                  admin_user, aadhaar_last4='5678', date_of_birth=DOB)
        link_profile(finished)

        stats = build_dashboard_summary(admin_user)['stats']

        assert stats['total_candidates'] == 1

    def test_the_card_and_the_list_it_links_to_report_the_same_people(
        self, admin_user, make_batch, make_candidate, client_for,
    ):
        """The invariant that makes the cards clickable rather than merely decorative: following
        a number must land on exactly the rows it counted.

        Both sides reach it through their own code - build_dashboard_summary aggregates, the
        list endpoint filters and paginates - so this is the only thing stopping them drifting.
        """
        for n in range(3):
            make_candidate(make_batch(admin_user), admin_user,
                           aadhaar_last4='90%02d' % n, date_of_birth=date(1997, 3, 1))
        make_candidate(make_batch(admin_user, status=Batch.Status.COMPLETED), admin_user,
                       aadhaar_last4='9900', date_of_birth=date(1996, 4, 2))

        stats = build_dashboard_summary(admin_user)['stats']
        listed = client_for(admin_user).get('/api/candidates/', {'batch_status': 'in_progress'})

        assert listed.status_code == 200
        assert stats['total_candidates'] == 3
        assert listed.data['count'] == stats['total_candidates']

    def test_the_completed_card_and_its_list_agree_too(
        self, admin_user, make_batch, make_candidate, make_invitation, client_for,
    ):
        """`status=completed` resolves through the latest attempt, not Candidate.status - which
        nothing ever writes COMPLETED to. Before this the link carried that parameter and the
        endpoint ignored it outright, so the card led to an unfiltered list.
        """
        running = make_batch(admin_user)
        finished = make_candidate(running, admin_user)
        ExamAttempt.objects.create(
            candidate=finished, invitation=make_invitation(finished, admin_user),
            status=ExamAttempt.Status.SUBMITTED, submitted_at=timezone.now(),
        )
        still_going = make_candidate(running, admin_user)
        ExamAttempt.objects.create(
            candidate=still_going, invitation=make_invitation(still_going, admin_user),
            status=ExamAttempt.Status.IN_PROGRESS,
        )

        stats = build_dashboard_summary(admin_user)['stats']
        listed = client_for(admin_user).get(
            '/api/candidates/', {'batch_status': 'in_progress', 'status': 'completed'})

        assert stats['completed'] == 1
        assert listed.data['count'] == stats['completed']
        assert listed.data['results'][0]['candidate_id'] == finished.candidate_id

    def test_an_unfiltered_list_is_still_everyone(
        self, admin_user, make_batch, make_candidate, client_for,
    ):
        """The scope is the card's, not the page's: All Candidates without the parameter must
        still show candidates from finished batches, or the only way to see them would be gone.
        """
        make_candidate(make_batch(admin_user), admin_user)
        make_candidate(make_batch(admin_user, status=Batch.Status.COMPLETED), admin_user)

        listed = client_for(admin_user).get('/api/candidates/')

        assert listed.data['count'] == 2
