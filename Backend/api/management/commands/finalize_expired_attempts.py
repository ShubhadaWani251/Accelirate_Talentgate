"""Safety net for exam attempts nobody ever revisits.

CandidateAttemptAuthentication already auto-finalizes an attempt the moment its own candidate
touches it again past the deadline, but an attempt whose candidate simply never comes back would
otherwise sit IN_PROGRESS forever. No Celery/broker is wired up in this project (see
services/exam_session.py's module docstring context) - this command is meant to be run instead
via any external scheduler (cron / Windows Task Scheduler / an Azure WebJob) every 5-15 minutes.

Two distinct cases are handled, because the clock only starts when the candidate opens the exam
window (services/exam_session.begin_exam):
  1. Begun but never finished - past started_at + exam_duration_minutes.
  2. Never begun at all - identity capture completed, then the candidate walked away. These have
     no deadline of their own, so the invitation's own link_expired_at is used instead: while the
     link is still valid they're legitimately allowed to come back and start.

Safe to run concurrently from more than one process - see _finalize_one_locked. finalize_attempt
itself is idempotent (a no-op once status isn't IN_PROGRESS), which covers a slow race, but not a
true simultaneous one: two processes could both read IN_PROGRESS before either writes and both
proceed, doing the scoring work twice. That specifically matters here because startup.sh's
scheduler loop runs on every App Service instance independently with no coordination between
them - a prerequisite for scaling the web tier out to more than one instance without touching
this code again.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from api.models import ExamAttempt
from api.services import exam_session


class Command(BaseCommand):
    help = 'Finalizes exam attempts still IN_PROGRESS past their deadline (or past link expiry).'

    def handle(self, *args, **options):
        now = timezone.now()
        attempts = ExamAttempt.objects.filter(status=ExamAttempt.Status.IN_PROGRESS)

        expired = abandoned = 0
        for attempt in attempts:
            outcome = self._finalize_one_locked(attempt.pk, now)
            if outcome == 'expired':
                expired += 1
            elif outcome == 'abandoned':
                abandoned += 1

        self.stdout.write(self.style.SUCCESS(
            f'Finalized {expired} timed-out attempt(s) and {abandoned} never-started attempt(s) '
            f'whose link expired.'
        ))

    def _finalize_one_locked(self, attempt_id, now):
        """Re-fetches and locks this one attempt with SELECT ... FOR UPDATE SKIP LOCKED before
        deciding anything, so a concurrent run of this same command (a second App Service
        instance) skips a row already being finalized elsewhere instead of racing it. Returns
        'expired', 'abandoned', or None (not eligible, or already claimed/finalized elsewhere).
        """
        with transaction.atomic():
            try:
                locked = (
                    ExamAttempt.objects.select_for_update(skip_locked=True)
                    .select_related('invitation', 'invitation__batch', 'candidate')
                    .get(pk=attempt_id)
                )
            except ExamAttempt.DoesNotExist:
                return None
            if locked.status != ExamAttempt.Status.IN_PROGRESS:
                return None

            if locked.started_at is not None:
                if exam_session.is_expired(locked):
                    exam_session.finalize_attempt(locked, outcome='submitted')
                    return 'expired'
                return None
            if locked.invitation.link_expired_at < now:
                # Never opened the exam window and can no longer do so. Scored as a submission
                # of zero answers rather than a proctoring termination - walking away isn't a
                # violation, and finalize_attempt is the single path that writes Candidate.result.
                exam_session.finalize_attempt(locked, outcome='submitted')
                return 'abandoned'
            return None
