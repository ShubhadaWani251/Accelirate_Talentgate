"""management/commands/purge_expired_revoked_tokens.py - the refresh-token denylist cleanup.

The denylist only has to outlive the token it lists: once a refresh token's own `exp` has passed
it is rejected by simplejwt regardless of whether the row is still here. Nothing performed this
cleanup before, so the table grew one row per logout and per refresh with no bound at all.

The invariant that actually matters is the negative one - a row whose token has NOT yet expired
must survive, because deleting it early would let a revoked-but-unexpired token be replayed.
"""
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from api.models import RevokedRefreshToken

pytestmark = pytest.mark.django_db


def _revoked(user, *, expires_in):
    return RevokedRefreshToken.objects.create(
        jti=f'jti-{timezone.now().timestamp()}-{expires_in.total_seconds()}',
        user=user,
        expires_at=timezone.now() + expires_in,
    )


class TestPurgeExpiredRevokedTokens:
    def test_an_expired_row_is_deleted(self, ta_user):
        stale = _revoked(ta_user, expires_in=timedelta(days=-1))

        call_command('purge_expired_revoked_tokens')

        assert not RevokedRefreshToken.objects.filter(pk=stale.pk).exists()

    def test_a_still_valid_row_is_kept(self, ta_user):
        """The load-bearing case: this token can still be presented, so its denylist entry is
        the only thing standing between a revoked token and a working session.
        """
        live = _revoked(ta_user, expires_in=timedelta(days=1))

        call_command('purge_expired_revoked_tokens')

        assert RevokedRefreshToken.objects.filter(pk=live.pk).exists()

    def test_dry_run_deletes_nothing(self, ta_user):
        stale = _revoked(ta_user, expires_in=timedelta(days=-1))

        call_command('purge_expired_revoked_tokens', '--dry-run')

        assert RevokedRefreshToken.objects.filter(pk=stale.pk).exists()
