"""Dashboard stat cards ("Total Candidates" etc.) count real PEOPLE, not batch appearances.

Reported live: "Total Candidates" was counting raw Candidate rows - one per batch upload of
the same person - while the All Candidates page itself already collapsed to one row per person
(see services/candidate_profile.py). The two now share one seam
(services/access.dedupe_by_profile) so they can't disagree again.
"""

from datetime import date

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
