"""Re-sends invitation emails that were queued but never actually sent.

Invitation emails go out on a daemon background thread inside the web worker (see
services/invites.send_invites_async). That keeps the send-invites request fast, but it means a
process shutdown - most commonly a deploy sending SIGTERM to the worker - kills the thread
mid-run. Every invitation it had not yet reached keeps email_status=QUEUED forever, with nothing
anywhere retrying it. The UI shows "Queued", which reads as "in flight", so the failure is
invisible: nobody finds out until a candidate says they never got a link.

This sweep closes that gap. It only picks up rows that have been QUEUED longer than a grace
period, because a row queued seconds ago is probably still in flight on a live thread and
re-sending it would deliver two emails for one invitation.

FAILED rows are deliberately left alone unless --include-failed is passed. A failure already has
its reason recorded on the row, and the common causes are permanent (an unverified sender
address, a mistyped candidate address): retrying those on a timer would re-attempt forever and
never fix anything, while a genuinely transient failure is better re-driven deliberately by
whoever fixed the cause.

    python manage.py retry_stalled_invite_emails
    python manage.py retry_stalled_invite_emails --dry-run
    python manage.py retry_stalled_invite_emails --include-failed --grace-minutes 60
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from api.models import Batch, Invitation
from api.services.invites import send_invite_and_record

logger = logging.getLogger(__name__)

# How long a row must have sat QUEUED before it is assumed abandoned. Comfortably longer than a
# large batch takes to send sequentially, so a slow-but-working run is never overtaken by this
# sweep - the cost of guessing wrong is a duplicate email to a candidate.
DEFAULT_GRACE_MINUTES = 15

# Bounds one run. A sweep that tried to re-send thousands of rows in a single scheduled tick
# would hold a worker for a long time and hammer the mail provider's rate limit; the remainder
# is simply picked up on the next tick.
DEFAULT_MAX_PER_RUN = 200


class Command(BaseCommand):
    help = 'Re-sends invitation emails left QUEUED by an interrupted send (e.g. a deploy).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be re-sent without sending anything.',
        )
        parser.add_argument(
            '--include-failed', action='store_true',
            help='Also retry rows marked FAILED. Use after fixing the underlying cause - '
                 'most failure reasons are permanent and will simply fail again.',
        )
        parser.add_argument(
            '--grace-minutes', type=int, default=DEFAULT_GRACE_MINUTES,
            help=f'Minimum age before a QUEUED row is considered stalled '
                 f'(default {DEFAULT_GRACE_MINUTES}).',
        )
        parser.add_argument(
            '--max', type=int, default=DEFAULT_MAX_PER_RUN, dest='max_per_run',
            help=f'Maximum number to re-send in one run (default {DEFAULT_MAX_PER_RUN}).',
        )

    def _eligible(self, cutoff, include_failed):
        statuses = [Invitation.EmailStatus.QUEUED]
        if include_failed:
            statuses.append(Invitation.EmailStatus.FAILED)

        # Rows that predated this column were stamped with the migration's own timestamp
        # (migration 0015), not left null, so they simply age past the grace period a few
        # minutes after deploy. The isnull branch is a guard for any row that somehow has no
        # timestamp - treating it as old is the safe reading, since the alternative is an
        # invitation that can never be retried.
        age_ok = Q(created_at__lt=cutoff) | Q(created_at__isnull=True)

        return (
            Invitation.objects
            .filter(age_ok, email_status__in=statuses)
            # Only batches that may still issue invitations. Sending a fresh assessment link for
            # a cancelled batch, or one still in Draft, is exactly what
            # services/invites.assert_batch_can_invite exists to prevent - enforced here as a
            # queryset filter so this sweep cannot reintroduce it.
            .filter(batch__status=Batch.Status.IN_PROGRESS)
            # A link that has already expired is dead: re-sending it emails the candidate
            # something that cannot be opened.
            .filter(link_expired_at__gt=timezone.now())
            # Someone already opened it, so the email plainly arrived and the status is just
            # stale. Re-sending would be pure noise.
            .filter(link_clicked_at__isnull=True, is_link_used=False)
            .exclude(candidate__email='')
            .exclude(candidate__email__isnull=True)
            .exclude(candidate__is_deleted=True)
            .select_related('candidate', 'batch')
            # Oldest first: the ones that have been waiting longest go out first when a run is
            # capped by --max.
            .order_by('invitation_id')
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(minutes=options['grace_minutes'])
        queryset = self._eligible(cutoff, options['include_failed'])
        total = queryset.count()
        pending = list(queryset[:options['max_per_run']])

        if not pending:
            self.stdout.write('No stalled invitation emails.')
            return

        if options['dry_run']:
            for invitation in pending:
                self.stdout.write(
                    f'  invitation_id={invitation.invitation_id} '
                    f'batch_id={invitation.batch_id} '
                    f'status={invitation.email_status} '
                    f'created_at={invitation.created_at.isoformat() if invitation.created_at else "unknown"}'
                )
            self.stdout.write(self.style.WARNING(
                f'[dry run] Would re-send {len(pending)} of {total} stalled invitation(s). '
                f'Nothing was sent.'
            ))
            return

        base_url = settings.FRONTEND_ORIGIN
        sent = failed = 0
        for invitation in pending:
            if send_invite_and_record(invitation, base_url):
                sent += 1
            else:
                # The reason is already recorded on the row and logged with a traceback by
                # send_invite_and_record; nothing to add here.
                failed += 1

        # Logged as well as printed: this runs unattended on a scheduler, where stdout may or
        # may not be collected, and "we silently re-sent 40 emails" is worth having a record of.
        logger.info(
            'retry_stalled_invite_emails: re-sent %s, failed %s, %s still pending',
            sent, failed, max(total - len(pending), 0),
        )

        message = f'Re-sent {sent} invitation email(s).'
        if failed:
            message += f' {failed} failed again - see each row\'s error for the reason.'
        if total > len(pending):
            message += (f' {total - len(pending)} more remain and will be picked up on the '
                        f'next run (--max was {options["max_per_run"]}).')
        style = self.style.WARNING if failed else self.style.SUCCESS
        self.stdout.write(style(message))
