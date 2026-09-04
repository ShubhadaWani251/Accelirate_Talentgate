"""Converts finished attempts' WebM proctoring recordings to MP4, for a TA whose browser or
network won't handle WebM comfortably - see services.video_transcode's module docstring for the
full reasoning (the original WebM stays untouched; this only ever adds a second file).

Only ever attempts SUBMITTED/TERMINATED attempts, never IN_PROGRESS ones: the WebM is an Azure
append blob that recording chunks are still being written to until the attempt is finalized, so
converting it mid-exam would either fail on a partial file or race a chunk upload landing during
the download. There is no urgency to running this often - unlike process_email_queue, nobody is
staring at a blank inbox waiting for a video to reprocess - so a modest interval (see the
schedulers this is wired into) is enough; running it more often just means less time between an
exam finishing and its MP4 being ready.

Concurrency: unlike process_email_queue's per-row lock held for the length of a quick network
call, holding a Postgres row lock for the length of an ffmpeg run (seconds to real minutes for a
full recording) would tie up a database connection for far too long. Instead, _claim_one_locked
below takes a SELECT ... FOR UPDATE SKIP LOCKED lock only long enough to increment
mp4_transcode_attempts and commit - the actual conversion runs fully unlocked afterwards. Two
instances can therefore both claim the same row an instant apart, before either one's transcode
has finished and written back a URL, and both end up converting the same recording once - wasted
CPU, but not a correctness problem (whichever save lands second simply wins, and both produce a
valid file). At this app's actual scale (see README's original 10-15 concurrent candidate load
context) that double-conversion is rare enough not to be worth a full in-progress status field to
close it completely.

    python manage.py transcode_recordings
    python manage.py transcode_recordings --dry-run
    python manage.py transcode_recordings --max 20
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from api.models import ExamAttempt
from api.services import video_transcode

# A recording that fails this many times stops being retried automatically - a permanently
# corrupt or unusual upload should not burn CPU on every scheduled tick forever. Matches
# INVITE_MAX_RETRY_ATTEMPTS's role in process_email_queue, just for this queue instead.
MAX_TRANSCODE_ATTEMPTS = 3

DEFAULT_MAX_PER_RUN = 20


class Command(BaseCommand):
    help = "Converts finished attempts' WebM proctoring recordings to MP4."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be converted without converting anything.',
        )
        parser.add_argument(
            '--max', type=int, default=DEFAULT_MAX_PER_RUN, dest='max_per_run',
            help=f'Maximum number to convert in one run (default {DEFAULT_MAX_PER_RUN}) - a '
                 f'real conversion can take a while, so a run is bounded the same way '
                 f'process_email_queue bounds a batch of sends.',
        )

    def _eligible(self):
        return (
            ExamAttempt.objects
            .filter(
                status__in=[ExamAttempt.Status.SUBMITTED, ExamAttempt.Status.TERMINATED],
                session_recording_url__isnull=False,
                session_recording_mp4_url__isnull=True,
                mp4_transcode_attempts__lt=MAX_TRANSCODE_ATTEMPTS,
            )
            .order_by('attempt_id')
        )

    def handle(self, *args, **options):
        pending = list(self._eligible()[:options['max_per_run']])

        if not pending:
            self.stdout.write('No recordings need converting.')
            return

        if options['dry_run']:
            for attempt in pending:
                self.stdout.write(
                    f'  attempt_id={attempt.attempt_id} '
                    f'attempts_so_far={attempt.mp4_transcode_attempts}'
                )
            self.stdout.write(self.style.WARNING(
                f'[dry run] Would attempt {len(pending)} conversion(s). Nothing was changed.'
            ))
            return

        converted = failed = skipped = 0
        for attempt in pending:
            outcome = self._convert_one(attempt.pk)
            if outcome == 'converted':
                converted += 1
            elif outcome == 'failed':
                failed += 1
            else:
                skipped += 1

        message = f'Converted {converted} recording(s) to MP4.'
        if failed:
            message += f' {failed} failed (see the log for ffmpeg output).'
        if skipped:
            message += f' {skipped} were already claimed by a concurrent run and skipped.'
        style = self.style.WARNING if failed else self.style.SUCCESS
        self.stdout.write(style(message))

    def _claim_one_locked(self, attempt_id):
        """Briefly locks and re-checks this one attempt's eligibility, then increments its
        attempt counter and releases the lock - see the module docstring for why the actual
        ffmpeg run must not happen while still holding this. Returns True if claimed (safe to
        proceed with a real conversion attempt), False if another run already claimed or
        finished it, or it is no longer eligible for some other reason.
        """
        with transaction.atomic():
            try:
                locked = ExamAttempt.objects.select_for_update(skip_locked=True).get(pk=attempt_id)
            except ExamAttempt.DoesNotExist:
                return False
            if locked.status not in (ExamAttempt.Status.SUBMITTED, ExamAttempt.Status.TERMINATED):
                return False
            if not locked.session_recording_url or locked.session_recording_mp4_url:
                return False
            if locked.mp4_transcode_attempts >= MAX_TRANSCODE_ATTEMPTS:
                return False
            locked.mp4_transcode_attempts += 1
            locked.save(update_fields=['mp4_transcode_attempts'])
            return True

    def _convert_one(self, attempt_id):
        if not self._claim_one_locked(attempt_id):
            return 'skipped'

        mp4_url = video_transcode.transcode_to_mp4(attempt_id)
        if mp4_url is None:
            return 'failed'

        ExamAttempt.objects.filter(pk=attempt_id).update(session_recording_mp4_url=mp4_url)
        return 'converted'
