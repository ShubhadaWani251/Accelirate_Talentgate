"""Re-grade finished attempts against the CURRENT rules and cutoffs.

Grading rules change. Borderline did not exist until 17-18 September 2026, so every attempt
finished before then was stored as a plain pass or fail and has never been looked at again -
a candidate who cleared three sections and missed the fourth by one mark sits there as FAIL,
which is exactly the outcome borderline was introduced to stop.

Nothing re-grades on its own. services.exam_session.regrade_batch runs only when a batch's
cutoffs actually CHANGE (views.batches._apply_section_cutoffs compares before writing), so
re-saving the same numbers on Batch Details does nothing - correctly, but it leaves no way to
say "apply today's rules to what is already there". This is that way.

    python manage.py regrade_results --dry-run          # every batch, report only
    python manage.py regrade_results --batch 443        # one batch
    python manage.py regrade_results                    # apply, all batches

Safe to run repeatedly: regrade_attempt returns False when nothing moved, and a result a human
decided by hand (Candidate.result_decided_by, only ever set on a borderline call) is never
overwritten.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from api.models import Batch, ExamAttempt
from api.services.exam_session import regrade_attempt


class _DryRun(Exception):
    """Raised to unwind the transaction a dry run did its work inside."""


class Command(BaseCommand):
    help = "Re-grade finished exam attempts against the batch's current cutoffs and rules."

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch', type=int, default=None,
            help='Only this batch id. Omit for every batch.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would change, then roll it back.',
        )

    def handle(self, *args, **options):
        batches = Batch.objects.filter(is_deleted=False)
        if options['batch'] is not None:
            batches = batches.filter(batch_id=options['batch'])
            if not batches.exists():
                raise CommandError(f"No batch {options['batch']}.")

        if not options['dry_run']:
            self._run(batches)
            return

        # regrade_attempt writes as it goes, so a dry run has to do the real work and then
        # unwind it - there is no "would this change" without recomputing, and recomputing is
        # what saves. An exception is the only thing that rolls an atomic block back.
        try:
            with transaction.atomic():
                self._run(batches, dry_run=True)
                raise _DryRun
        except _DryRun:
            self.stdout.write(self.style.WARNING(
                'DRY RUN - nothing was saved. Re-run without --dry-run to apply.'
            ))

    def _run(self, batches, dry_run=False):
        attempts = (
            ExamAttempt.objects
            .select_related('candidate', 'invitation__batch')
            .filter(
                invitation__batch__in=batches,
                status__in=(ExamAttempt.Status.SUBMITTED, ExamAttempt.Status.TERMINATED),
            )
            .order_by('invitation__batch_id', 'attempt_id')
        )

        total, changed, decided_by_hand = 0, 0, 0
        for attempt in attempts:
            total += 1
            before = attempt.candidate.result
            if attempt.candidate.result_decided_by_id:
                decided_by_hand += 1
            if not regrade_attempt(attempt, attempt.invitation.batch):
                continue
            attempt.candidate.refresh_from_db(fields=['result'])
            if attempt.candidate.result != before:
                changed += 1
                self.stdout.write(
                    f'  batch {attempt.invitation.batch_id}: {attempt.candidate.full_name} '
                    f'{before} -> {attempt.candidate.result}'
                )

        verb = 'would change' if dry_run else 'changed'
        self.stdout.write(self.style.SUCCESS(
            f'Re-graded {total} attempt(s); {changed} result(s) {verb}.'
        ))
        if decided_by_hand:
            self.stdout.write(
                f'{decided_by_hand} candidate(s) had a result decided by hand - scores and '
                f'section flags were recomputed, the human call was left alone.'
            )
