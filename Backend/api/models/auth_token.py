from django.db import models
from django.utils import timezone

from .users import User


class RevokedRefreshToken(models.Model):
    """Denylist of refresh-token JTIs, checked on /api/auth/refresh/.

    Kept separate from rest_framework_simplejwt's own token_blacklist app,
    whose OutstandingToken/BlacklistedToken models FK to AUTH_USER_MODEL
    (django.contrib.auth.User) rather than api.User.
    """
    jti = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column='user_id')
    revoked_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(help_text="Copy of the token's own expiry, for cleanup")

    class Meta:
        db_table = 'revoked_refresh_tokens'
        indexes = [
            models.Index(fields=['jti'], name='ix_revoked_jti'),
        ]

    def __str__(self):
        return f"Revoked {self.jti} ({self.user.email})"
