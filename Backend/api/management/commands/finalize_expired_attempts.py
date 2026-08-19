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
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import ExamAttempt
from api.services import exam_session


class Command(BaseCommand):
    help = 'Finalizes exam attempts still IN_PROGRESS past their deadline (or past link expiry).'

    def handle(self, *args, **options):
        now = timezone.now()
        attempts = ExamAttempt.objects.select_related(
            'invitation', 'invitation__batch', 'candidate',
        ).filter(status=ExamAttempt.Status.IN_PROGRESS)

        expired = abandoned = 0
        for attempt in attempts:
            if attempt.started_at is not None:
                if exam_session.is_expired(attempt):
                    exam_session.finalize_attempt(attempt, outcome='submitted')
                    expired += 1
            elif attempt.invitation.link_expired_at < now:
                # Never opened the exam window and can no longer do so. Scored as a submission of
                # zero answers rather than a proctoring termination - walking away isn't a
                # violation, and finalize_attempt is the single path that writes Candidate.result.
                exam_session.finalize_attempt(attempt, outcome='submitted')
                abandoned += 1

        self.stdout.write(self.style.SUCCESS(
            f'Finalized {expired} timed-out attempt(s) and {abandoned} never-started attempt(s) '
            f'whose link expired.'
        ))
