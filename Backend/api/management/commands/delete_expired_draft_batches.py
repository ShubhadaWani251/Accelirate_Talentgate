"""Deletes Draft batches that were never finalized within 24 hours of creation.

This is the authoritative layer of the draft-expiry rule (see services/draft_expiry.py for the
other two and why they overlap): it runs regardless of whether anyone is logged in, whether any
browser is open, or whether the expired batch is ever requested again.

No Celery broker is configured in this project - celery/django-celery-beat sit unused in
requirements.txt with nothing wired up in settings.py - so this follows the same pattern the
existing `finalize_expired_attempts` command uses: a plain management command driven by whatever
scheduler the deployment already has (cron, Windows Task Scheduler, an Azure WebJob). Every
15-60 minutes is ample; the rule is "past 24 hours", not "at exactly 24 hours", and the
lazy-delete layer covers anyone who touches an expired draft between ticks.

    python manage.py delete_expired_draft_batches
    python manage.py delete_expired_draft_batches --dry-run
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from api.services import draft_expiry


class Command(BaseCommand):
    help = 'Deletes Draft batches (and their staged candidates) older than 24 hours.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be deleted without deleting anything.',
        )

    def handle(self, *args, **options):
        now = timezone.now()

        if options['dry_run']:
            # Counted per batch rather than with one aggregate, so the output names each batch
            # the sweep would take - the thing worth checking before running it for real.
            batches = list(draft_expiry.expired_drafts_queryset(now))
            if not batches:
                self.stdout.write('No expired draft batches.')
                return
            total_candidates = 0
            for batch in batches:
                count = batch.candidate_set.count()
                total_candidates += count
                self.stdout.write(
                    f'  batch_id={batch.batch_id} created_at={batch.created_at.isoformat()} '
                    f'expired_at={draft_expiry.draft_expires_at(batch).isoformat()} '
                    f'candidates={count}'
                )
            self.stdout.write(self.style.WARNING(
                f'[dry run] Would delete {len(batches)} draft batch(es) and '
                f'{total_candidates} candidate(s). Nothing was deleted.'
            ))
            return

        result = draft_expiry.delete_expired_draft_batches(now)
        message = (
            f'Deleted {result["batches_deleted"]} expired draft batch(es) and '
            f'{result["candidates_deleted"]} associated candidate(s).'
        )
        if result['skipped']:
            # Finalized or deleted between being listed and being locked - the race guard
            # working as intended, not an error.
            message += f' Skipped {result["skipped"]} no longer eligible.'
        if result['failed']:
            self.stdout.write(self.style.ERROR(
                f'{message} FAILED on {result["failed"]} batch(es) - see the log for details.'
            ))
            return
        self.stdout.write(self.style.SUCCESS(message))
