"""OCR fallback for Aadhaar verification, for id_photos the fast QR path (see
services.aadhaar.verify_identity_photo) left PENDING - no readable QR, or a Secure QR this
codebase deliberately does not parse (see services.aadhaar.parse_secure_qr).

Modeled directly on transcode_recordings.py's own claim-then-release pattern, for the same
reason: OCR (a real ML engine or a hosted API call) can take real seconds, and holding a Postgres
row lock for that long would tie up a database connection far too long. _claim_one_locked takes a
SELECT ... FOR UPDATE SKIP LOCKED lock only long enough to increment
aadhaar_verification_attempts and commit - the actual OCR call runs fully unlocked afterwards.
Two instances can therefore both claim the same row an instant apart and both end up OCRing the
same photo once - wasted work, but not a correctness problem, same as that module's own
reasoning.

    python manage.py verify_aadhaar_ocr_fallback
    python manage.py verify_aadhaar_ocr_fallback --dry-run
    python manage.py verify_aadhaar_ocr_fallback --max 20
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from api.models import ExamAttempt
from api.services import aadhaar

# An id_photo that fails this many times stops being retried automatically - a genuinely unreadable
# photo should not burn CPU/API calls on every scheduled tick forever. Matches
# MAX_TRANSCODE_ATTEMPTS's role in transcode_recordings.py, just for this queue instead.
MAX_VERIFICATION_ATTEMPTS = 3

DEFAULT_MAX_PER_RUN = 20


class Command(BaseCommand):
    help = 'OCR fallback for Aadhaar verification on identity photos with no readable QR.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be processed without processing anything.',
        )
        parser.add_argument(
            '--max', type=int, default=DEFAULT_MAX_PER_RUN, dest='max_per_run',
            help=f'Maximum number to process in one run (default {DEFAULT_MAX_PER_RUN}).',
        )

    def _eligible(self):
        return (
            ExamAttempt.objects
            .filter(
                aadhaar_verification_status=ExamAttempt.AadhaarVerificationStatus.PENDING,
                aadhaar_capture_url__isnull=False,
                aadhaar_verification_attempts__lt=MAX_VERIFICATION_ATTEMPTS,
            )
            .exclude(aadhaar_capture_url='')
            .order_by('attempt_id')
        )

    def handle(self, *args, **options):
        if not settings.AADHAAR_VERIFICATION_ENABLED:
            self.stdout.write('AADHAAR_VERIFICATION_ENABLED is off - nothing to do.')
            return

        pending = list(self._eligible()[:options['max_per_run']])

        if not pending:
            self.stdout.write('No identity photos need OCR verification.')
            return

        if options['dry_run']:
            for attempt in pending:
                self.stdout.write(
                    f'  attempt_id={attempt.attempt_id} '
                    f'attempts_so_far={attempt.aadhaar_verification_attempts}'
                )
            self.stdout.write(self.style.WARNING(
                f'[dry run] Would attempt {len(pending)} verification(s). Nothing was changed.'
            ))
            return

        verified = unreadable = skipped = 0
        for attempt in pending:
            outcome = self._process_one(attempt.pk)
            if outcome == 'verified':
                verified += 1
            elif outcome == 'still_unreadable':
                unreadable += 1
            else:
                skipped += 1

        message = f'Verified {verified} identity photo(s) via OCR.'
        if unreadable:
            message += f' {unreadable} still unreadable (will retry up to {MAX_VERIFICATION_ATTEMPTS} times).'
        if skipped:
            message += f' {skipped} were already claimed by a concurrent run and skipped.'
        self.stdout.write(self.style.SUCCESS(message))

    def _claim_one_locked(self, attempt_id):
        """Briefly locks and re-checks this one attempt's eligibility, then increments its
        attempt counter and releases the lock - see the module docstring for why the actual OCR
        call must not happen while still holding this. Returns True if claimed (safe to proceed),
        False if another run already claimed it or it is no longer eligible.
        """
        with transaction.atomic():
            try:
                locked = ExamAttempt.objects.select_for_update(skip_locked=True).get(pk=attempt_id)
            except ExamAttempt.DoesNotExist:
                return False
            if locked.aadhaar_verification_status != ExamAttempt.AadhaarVerificationStatus.PENDING:
                return False
            if not locked.aadhaar_capture_url:
                return False
            if locked.aadhaar_verification_attempts >= MAX_VERIFICATION_ATTEMPTS:
                return False
            locked.aadhaar_verification_attempts += 1
            locked.save(update_fields=['aadhaar_verification_attempts'])
            return True

    def _process_one(self, attempt_id):
        if not self._claim_one_locked(attempt_id):
            return 'skipped'
        attempt = ExamAttempt.objects.select_related('candidate').get(pk=attempt_id)
        return aadhaar.run_ocr_fallback(attempt)
