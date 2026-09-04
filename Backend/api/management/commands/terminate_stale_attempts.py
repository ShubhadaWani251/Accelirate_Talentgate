"""Catches a candidate's Safe Exam Browser (or plain browser tab) closing mid-exam.

There is no JS event that reliably survives a process being closed or killed - `beforeunload`/
`pagehide` fire for an ordinary page refresh too, and this app explicitly supports refreshing
mid-exam (see ExamAttemptPage's cameraAcquired/fullscreenReady re-gates), so treating either as
proof of abandonment would wrongly terminate a candidate who did nothing wrong. The only signal
that actually distinguishes "closed and gone" from "reloaded and coming right back" is silence
over time: ExamAttempt.last_activity_at is stamped by CandidateAttemptAuthentication on every
authenticated request, and the ~10s recording-chunk upload alone means that stamp normally never
goes stale for more than a few seconds while the candidate's browser is genuinely still running.
This command watches for it going stale anyway.

Deliberately excludes an attempt that has simply run past its own exam_duration_minutes -
finalize_expired_attempts already owns that case (scored as a normal 'submitted' outcome, not a
proctoring violation), and an attempt that is both stale AND past its deadline is exactly as
likely to be "candidate finished and walked away" as "candidate closed early", so this command
defers to the existing, less presumptive handling for that case entirely.

Not optional in any deployment that wants this signal at all - see startup.sh / crontab.example /
register-scheduled-tasks.ps1 / docker-compose.yml, all four of which schedule this alongside the
other two housekeeping commands. Safe to run concurrently from more than one process:
record_violation does its own SELECT ... FOR UPDATE before deciding anything, so two instances
racing the same row just means the second one's lock waits, re-checks under it, and finds nothing
left to do (see its own docstring) - no extra locking is needed here on top of that.

    python manage.py terminate_stale_attempts
    python manage.py terminate_stale_attempts --dry-run
    python manage.py terminate_stale_attempts --threshold-seconds 90
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import ExamAttempt
from api.services import exam_session

# Generous relative to the ~10s recording-chunk cadence that normally keeps last_activity_at
# fresh - covers a slow network, a brief tab-switch-triggered pause in recording, or an ordinary
# page refresh (which takes a few seconds, not a minute) without mistaking any of those for a
# genuine close.
DEFAULT_THRESHOLD_SECONDS = 60


class Command(BaseCommand):
    help = ('Terminates in-progress exam attempts whose browser/SEB has gone silent mid-exam '
            '(closed before submitting), as distinct from one that simply ran out of time.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be terminated without changing anything.',
        )
        parser.add_argument(
            '--threshold-seconds', type=int, default=DEFAULT_THRESHOLD_SECONDS,
            help=f'How long without any authenticated request before an attempt counts as '
                 f'stale (default {DEFAULT_THRESHOLD_SECONDS}).',
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(seconds=options['threshold_seconds'])
        candidates = (
            ExamAttempt.objects
            .filter(
                status=ExamAttempt.Status.IN_PROGRESS,
                started_at__isnull=False,
                last_activity_at__lt=cutoff,
            )
            .select_related('invitation__batch', 'candidate')
        )

        if options['dry_run']:
            stale = [a for a in candidates if not exam_session.is_expired(a)]
            for attempt in stale:
                self.stdout.write(
                    f'  attempt_id={attempt.attempt_id} '
                    f'candidate={attempt.candidate.email} '
                    f'last_activity_at={attempt.last_activity_at.isoformat()}'
                )
            self.stdout.write(self.style.WARNING(
                f'[dry run] Would terminate {len(stale)} stale attempt(s). Nothing was changed.'
            ))
            return

        terminated = 0
        for attempt in candidates:
            # Own deadline takes priority over silence - see the module docstring for why this
            # command steps aside for finalize_expired_attempts rather than double-handling it.
            if exam_session.is_expired(attempt):
                continue
            result = exam_session.record_violation(attempt, exam_session.TerminationReason.WINDOW_CLOSED)
            if result['action'] == 'terminated':
                terminated += 1

        self.stdout.write(self.style.SUCCESS(
            f'Terminated {terminated} stale attempt(s) (browser/SEB closed mid-exam).'
        ))
