"""Deletes proctoring evidence (ID/face photos, session recording) older than the retention
window (30 days by default - see services/evidence_retention.py).

No Celery broker is configured in this project, so this follows the same pattern as the other
scheduled-cleanup command (finalize_expired_attempts): a plain management command driven by
whatever scheduler the deployment already has (cron, Windows Task Scheduler, an Azure WebJob).
Once a day is ample for a 30-day window.

    python manage.py purge_expired_evidence
    python manage.py purge_expired_evidence --dry-run
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from api.services import evidence_retention


class Command(BaseCommand):
    help = 'Deletes ID/face photos and session recordings older than the retention window.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be purged without deleting anything.',
        )

    def handle(self, *args, **options):
        now = timezone.now()

        if options['dry_run']:
            attempts = list(evidence_retention.expired_evidence_queryset(now))
            if not attempts:
                self.stdout.write('No expired evidence.')
                return
            for attempt in attempts:
                self.stdout.write(
                    f'  attempt_id={attempt.attempt_id} started_at={attempt.started_at.isoformat()}'
                )
            self.stdout.write(self.style.WARNING(
                f'[dry run] Would purge evidence for {len(attempts)} attempt(s). '
                f'Nothing was deleted.'
            ))
            return

        purged = evidence_retention.purge_expired_evidence(now)
        self.stdout.write(self.style.SUCCESS(
            f'Purged evidence for {purged} attempt(s) older than '
            f'{evidence_retention.RETENTION_DAYS} days.'
        ))
