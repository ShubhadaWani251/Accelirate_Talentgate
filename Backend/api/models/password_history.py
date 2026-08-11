from django.db import models
from django.utils import timezone

from .users import User


class PasswordHistoryEntry(models.Model):
    """Archive of a user's past password hashes, so a change/reset can be checked
    against recent history rather than just the single current password.
    See api/services/passwords.py for the check + pruning logic.
    """
    history_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column='user_id',
                             related_name='password_history')
    password_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'password_history'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at'], name='ix_pwdhist_user_created'),
        ]

    def __str__(self):
        return f'Password history #{self.history_id} for {self.user.email}'
