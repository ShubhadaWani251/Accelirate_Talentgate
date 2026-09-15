"""Real incident: a candidate abandoned an invitation right after Aadhaar capture (never began
the timed exam, so started_at stayed null), was re-invited, and completed the exam on the second
attempt. The candidate's Detail page showed no photo/recording and status "In Progress" - because
`ORDER BY started_at DESC` sorts a null started_at as the LARGEST value in Postgres (the
production database), so the abandoned attempt outranked the completed one. Fixed by ordering on
attempt_id (a BigAutoField, never null, and increasing with creation order) instead. See
serializers/candidates._latest_attempt.

This suite's own test database is SQLite (config/settings_test.py), which sorts null as the
SMALLEST value - the opposite of Postgres - so a null-started_at test case would pass under the
old, buggy `-started_at` ordering too and prove nothing here. Both tests below instead give the
two attempts non-null, deliberately CONFLICTING started_at/attempt_id order, so they only pass
when the code sorts by attempt_id - reproducing the fix (and the regression it guards against)
independently of either database's null-sort direction.
"""
from datetime import timedelta

from django.utils import timezone

from api.models import ExamAttempt


def _candidate_whose_earlier_attempt_has_a_later_started_at(
    ta_user, make_batch, make_candidate, make_invitation,
):
    """Attempt A: created first (lower attempt_id), abandoned, but stamped with a started_at
    later than B's - only possible to construct directly in a test, but it's exactly what's
    needed to tell "ordered by attempt_id" and "ordered by started_at" apart without relying on
    either database's null-sort direction. Attempt B: created second (higher attempt_id), the
    real completed one, with evidence and a score.
    """
    batch = make_batch(ta_user)
    candidate = make_candidate(batch, ta_user)
    now = timezone.now()

    abandoned_invitation = make_invitation(candidate, ta_user)
    ExamAttempt.objects.create(
        candidate=candidate, invitation=abandoned_invitation,
        status=ExamAttempt.Status.IN_PROGRESS,
        started_at=now,
        aadhaar_capture_url='https://example.test/attempts/abandoned/id_photo.jpg',
    )

    completed_invitation = make_invitation(candidate, ta_user)
    completed = ExamAttempt.objects.create(
        candidate=candidate, invitation=completed_invitation,
        status=ExamAttempt.Status.SUBMITTED,
        started_at=now - timedelta(minutes=1),
        submitted_at=now,
        face_photo_url='https://example.test/attempts/completed/face_photo.jpg',
        session_recording_url='https://example.test/attempts/completed/session_recording.webm',
        overall_score=40,
    )
    return candidate, completed


class TestLatestAttemptIsTheMostRecentlyCreatedNotTheMostRecentlyStarted:
    def test_candidate_detail_shows_the_completed_attempt_not_the_abandoned_one(
        self, ta_user, client_for, make_batch, make_candidate, make_invitation,
    ):
        candidate, completed = _candidate_whose_earlier_attempt_has_a_later_started_at(
            ta_user, make_batch, make_candidate, make_invitation,
        )

        response = client_for(ta_user).get('/api/candidates/%d/' % candidate.candidate_id)

        assert response.status_code == 200, response.data
        assert response.data['status'] == 'completed'
        assert response.data['status_display'] == 'Completed'
        assert response.data['evidence']['face_photo_url'] == completed.face_photo_url
        assert response.data['evidence']['session_recording_url'] == completed.session_recording_url

    def test_candidate_list_shows_the_completed_attempt_not_the_abandoned_one(
        self, ta_user, client_for, make_batch, make_candidate, make_invitation,
    ):
        candidate, completed = _candidate_whose_earlier_attempt_has_a_later_started_at(
            ta_user, make_batch, make_candidate, make_invitation,
        )

        response = client_for(ta_user).get('/api/candidates/?batch_id=%d' % candidate.batch_id)

        assert response.status_code == 200, response.data
        row = next(r for r in response.data['results'] if r['candidate_id'] == candidate.candidate_id)
        assert row['status'] == 'completed'
        assert row['overall_score'] == 40
