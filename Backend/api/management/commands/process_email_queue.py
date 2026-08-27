"""The invitation-email queue worker. This is the ONLY thing that actually sends a candidate's
assessment link - creating an Invitation row (services/invites.create_invitations /
create_single_reinvite) just queues it (email_status=QUEUED); nothing sends it inline from the
request that created it.

This replaced an in-process background thread (send_invites_async, since removed) that fired
sends the moment "Send Invite" was clicked, with a periodic sweep as a backup for whatever the
thread hadn't reached before a worker restart killed it. That shape had two send paths with
independent logic that could drift, and the backup's own "has this been queued long enough to be
considered stalled" heuristic existed only because a live thread might still be mid-run - a
problem that stops existing once there is no live thread. One path, one piece of logic: this
command IS the send path, not a fallback for one.

Consequently this is not optional in the way the old sweep was "nice to have as a safety net" -
without it running frequently, queued invitations simply never go out. Schedule it every 1-2
minutes (see deploy/crontab.example / deploy/register-scheduled-tasks.ps1), not the 15-30 minute
interval the old sweep used - that cadence was fine for an occasional backup and would now mean
candidates waiting minutes for a link that used to arrive within seconds of the click.

FAILED rows are deliberately left alone unless --include-failed is passed. A failure already has
its reason recorded on the row, and the common causes are permanent (an unverified sender
address, a mistyped candidate address): retrying those on a timer would re-attempt forever and
never fix anything, while a genuinely transient failure is better re-driven deliberately by
whoever fixed the cause.

retry_count is incremented only when re-attempting a row that has already failed at least once -
a QUEUED row's first attempt is not a retry of anything, however long it sat in the queue before
this command reached it. Once a row's retry_count reaches settings.INVITE_MAX_RETRY_ATTEMPTS it
stops being picked up automatically at all (--ignore-retry-limit overrides this for a deliberate
one-off push), so a permanently bad address is not retried forever.

Sends within one run are paced by settings.INVITE_SEND_DELAY_SECONDS - a burst of near-identical
emails reads as bulk/spam activity to the RECEIVING mail system, independent of whatever rate
Graph itself would allow.

    python manage.py process_email_queue
    python manage.py process_email_queue --dry-run
    python manage.py process_email_queue --include-failed
    python manage.py process_email_queue --include-failed --ignore-retry-limit
    python manage.py process_email_queue --max 500
"""

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import Batch, Invitation
from api.services.invites import send_invite_and_record

logger = logging.getLogger(__name__)

# Bounds one run. A run that tried to send thousands of rows in a single scheduled tick would
# hold the process for a long time and hammer the mail provider; the remainder is simply picked
# up on the next tick, seconds to minutes later depending on the schedule.
DEFAULT_MAX_PER_RUN = 200


class Command(BaseCommand):
    help = 'Sends every queued invitation email - the only thing that actually sends one.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be sent without sending anything.',
        )
        parser.add_argument(
            '--include-failed', action='store_true',
            help='Also retry rows marked FAILED. Use after fixing the underlying cause - '
                 'most failure reasons are permanent and will simply fail again.',
        )
        parser.add_argument(
            '--ignore-retry-limit', action='store_true',
            help='Also retry rows that have already hit INVITE_MAX_RETRY_ATTEMPTS '
                 f'(default {settings.INVITE_MAX_RETRY_ATTEMPTS}). For a deliberate manual push '
                 'after fixing whatever was causing the repeated failures - not for routine use, '
                 'since the limit exists specifically to stop a permanently bad address being '
                 'retried forever.',
        )
        parser.add_argument(
            '--max', type=int, default=DEFAULT_MAX_PER_RUN, dest='max_per_run',
            help=f'Maximum number to send in one run (default {DEFAULT_MAX_PER_RUN}).',
        )

    def _eligible(self, include_failed, ignore_retry_limit):
        statuses = [Invitation.EmailStatus.QUEUED]
        if include_failed:
            statuses.append(Invitation.EmailStatus.FAILED)

        queryset = (
            Invitation.objects
            .filter(email_status__in=statuses)
            # Only batches that may still issue invitations. Sending a fresh assessment link for
            # a cancelled batch, or one still in Draft, is exactly what
            # services/invites.assert_batch_can_invite exists to prevent - enforced here as a
            # queryset filter so this worker cannot reintroduce it.
            .filter(batch__status=Batch.Status.IN_PROGRESS)
            # A link that has already expired is dead: sending it emails the candidate something
            # that cannot be opened.
            .filter(link_expired_at__gt=timezone.now())
            # Someone already opened it - the email plainly arrived, so re-sending would be pure
            # noise. (Only relevant for a FAILED row being retried; a QUEUED row can never have
            # this set - nothing marks a link clicked before its email exists.)
            .filter(link_clicked_at__isnull=True, is_link_used=False)
            .exclude(candidate__email='')
            .exclude(candidate__email__isnull=True)
            .exclude(candidate__is_deleted=True)
            .select_related('candidate', 'batch')
            # Oldest first: whoever has been waiting longest goes out first when a run is capped
            # by --max.
            .order_by('invitation_id')
        )
        if not ignore_retry_limit:
            queryset = queryset.filter(retry_count__lt=settings.INVITE_MAX_RETRY_ATTEMPTS)
        return queryset

    def handle(self, *args, **options):
        queryset = self._eligible(options['include_failed'], options['ignore_retry_limit'])
        total = queryset.count()
        pending = list(queryset[:options['max_per_run']])

        if not pending:
            self.stdout.write('No queued invitation emails.')
            return

        if options['dry_run']:
            for invitation in pending:
                self.stdout.write(
                    f'  invitation_id={invitation.invitation_id} '
                    f'batch_id={invitation.batch_id} '
                    f'status={invitation.email_status} '
                    f'retry_count={invitation.retry_count}'
                )
            self.stdout.write(self.style.WARNING(
                f'[dry run] Would send {len(pending)} of {total} queued invitation(s). '
                f'Nothing was sent.'
            ))
            return

        base_url = settings.FRONTEND_ORIGIN
        sent = failed = 0
        for i, invitation in enumerate(pending):
            if i > 0 and settings.INVITE_SEND_DELAY_SECONDS > 0:
                time.sleep(settings.INVITE_SEND_DELAY_SECONDS)
            if invitation.email_status == Invitation.EmailStatus.FAILED:
                invitation.retry_count += 1
                invitation.save(update_fields=['retry_count'])
            if send_invite_and_record(invitation, base_url):
                sent += 1
            else:
                # The reason is already recorded on the row and logged with a traceback by
                # send_invite_and_record; nothing to add here.
                failed += 1

        # Logged as well as printed: this runs unattended on a scheduler, where stdout may or
        # may not be collected, and "we sent 40 invitations just now" is worth having a record of.
        logger.info(
            'process_email_queue: sent %s, failed %s, %s still pending',
            sent, failed, max(total - len(pending), 0),
        )

        message = f'Sent {sent} invitation email(s).'
        if failed:
            message += f' {failed} failed - see each row\'s error for the reason.'
        if total > len(pending):
            message += (f' {total - len(pending)} more remain and will be picked up on the '
                        f'next run (--max was {options["max_per_run"]}).')
        style = self.style.WARNING if failed else self.style.SUCCESS
        self.stdout.write(style(message))
