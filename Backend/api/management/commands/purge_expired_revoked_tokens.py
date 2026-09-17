"""Deletes RevokedRefreshToken rows whose underlying token has already expired.

The denylist exists so a refresh token revoked at logout (or rotated out by a refresh) cannot be
replayed before its natural expiry - see services/tokens.py. Once that expiry has passed the row
has no remaining purpose: the token is rejected by its own `exp` claim whether or not it is still
listed here, so keeping it changes nothing except the size of the table.

RevokedRefreshToken.expires_at is stored specifically to make this cleanup possible ("Copy of the
token's own expiry, for cleanup" - see api/models/auth_token.py), but nothing ever performed it,
so the table grew by one row per logout and per refresh, forever, with no upper bound.

Same shape as the other scheduled-cleanup commands (purge_expired_evidence,
finalize_expired_attempts): a plain management command driven by whatever scheduler the
deployment already has. Once a day is ample - nothing breaks if it lags, the rows are simply
still there.

    python manage.py purge_expired_revoked_tokens
    python manage.py purge_expired_revoked_tokens --dry-run
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import RevokedRefreshToken


class Command(BaseCommand):
    help = 'Deletes denylist rows for refresh tokens that have already expired on their own.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report how many rows would be deleted without deleting anything.',
        )

    def handle(self, *args, **options):
        # Strictly less-than: a row whose expiry is exactly now is still (just) load-bearing.
        expired = RevokedRefreshToken.objects.filter(expires_at__lt=timezone.now())

        if options['dry_run']:
            count = expired.count()
            self.stdout.write(self.style.WARNING(
                f'[dry run] Would delete {count} expired revoked-token row(s). '
                f'Nothing was deleted.'
            ))
            return

        deleted, _ = expired.delete()
        self.stdout.write(self.style.SUCCESS(
            f'Deleted {deleted} expired revoked-token row(s).'
        ))
