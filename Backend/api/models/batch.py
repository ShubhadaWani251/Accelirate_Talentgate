from django.db import models
from django.utils import timezone
from .users import User


class Batch(models.Model):
    """One row per candidate batch/drive."""
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        IN_PROGRESS = 'in_progress', 'In Progress'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'

    batch_id = models.BigAutoField(primary_key=True)
    batch_name = models.CharField(max_length=150)
    college_name = models.CharField(max_length=150)
    link_valid_from = models.DateTimeField()
    link_valid_until = models.DateTimeField()

    # Exam configuration
    logical_questions = models.SmallIntegerField(default=10)
    quantitative_questions = models.SmallIntegerField(default=10)
    verbal_questions = models.SmallIntegerField(default=10)
    programming_questions = models.SmallIntegerField(default=10)

    logical_cutoff = models.DecimalField(max_digits=5, decimal_places=2, default=70.00)
    quantitative_cutoff = models.DecimalField(max_digits=5, decimal_places=2, default=70.00)
    verbal_cutoff = models.DecimalField(max_digits=5, decimal_places=2, default=70.00)
    programming_cutoff = models.DecimalField(max_digits=5, decimal_places=2, default=70.00)

    exam_duration_minutes = models.SmallIntegerField(default=45)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)

    primary_ta_user = models.ForeignKey(User, on_delete=models.PROTECT,
                                        db_column='primary_ta_user_id',
                                        related_name='primary_batches')
    total_candidates = models.IntegerField(default=0)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL,
                                   null=True, db_column='created_by',
                                   related_name='created_batches')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        db_table = 'batches'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status'], name='ix_batches_status'),
        ]

    def __str__(self):
        return self.batch_name