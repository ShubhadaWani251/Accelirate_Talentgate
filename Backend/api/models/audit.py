from django.db import models
from django.utils import timezone
from .users import User


class AuditLog(models.Model):
    """Append-only event log with review workflow."""
    log_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL,
                             null=True, db_column='user_id')
    action_type = models.CharField(max_length=40,
                                   help_text="e.g. login, create, update, delete")
    entity_type = models.CharField(max_length=40,
                                   help_text="user | batch | candidate | question | invitation")
    entity_id = models.BigIntegerField(help_text="PK of affected row")
    action_details = models.JSONField(null=True, blank=True)

    # Review workflow
    requires_review = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL,
                                    null=True, db_column='reviewed_by',
                                    related_name='reviewed_logs')
    reviewed_at = models.DateTimeField(null=True, blank=True)

    ip_address = models.CharField(max_length=45, null=True, blank=True)
    user_agent = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'audit_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['entity_type', 'entity_id', 'created_at'],
                        name='ix_audit_entity'),
            models.Index(fields=['requires_review', 'reviewed_at'],
                        name='ix_audit_review'),
        ]

    def __str__(self):
        return f"Log #{self.log_id} - {self.action_type} on {self.entity_type}"