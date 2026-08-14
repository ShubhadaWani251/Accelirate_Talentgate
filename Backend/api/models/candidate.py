from django.db import models
from django.utils import timezone
from .users import User
from .batch import Batch


class Candidate(models.Model):
    """One row per candidate profile within a batch."""
    class ValidationStatus(models.TextChoices):
        OK = 'ok', 'OK'
        MISSING_EMAIL = 'missing_email', 'Missing Email'
        MISSING_AADHAAR = 'missing_aadhaar', 'Missing Aadhaar'
        MISSING_NAME = 'missing_name', 'Missing Name'
        MISSING_COLLEGE = 'missing_college', 'Missing College'

    class Status(models.TextChoices):
        PENDING_INVITE = 'pending_invite', 'Pending Invite'
        INVITED = 'invited', 'Invited'
        IN_PROGRESS = 'in_progress', 'In Progress'
        COMPLETED = 'completed', 'Completed'
        TERMINATED = 'terminated', 'Terminated'
        NO_SHOW = 'no_show', 'No Show'

    class Result(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PASS = 'pass', 'Pass'
        FAIL = 'fail', 'Fail'

    candidate_id = models.BigAutoField(primary_key=True)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80, null=True, blank=True)
    email = models.EmailField(max_length=150)
    phone = models.CharField(max_length=20, null=True, blank=True)
    aadhaar_number = models.CharField(max_length=255)

    # Education
    college_name = models.CharField(max_length=150, null=True, blank=True)
    degree = models.CharField(max_length=50, null=True, blank=True)
    stream = models.CharField(max_length=100, null=True, blank=True)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    passing_out_year = models.SmallIntegerField(null=True, blank=True)
    location = models.CharField(max_length=100, null=True, blank=True)

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, db_column='batch_id')
    upload_row_number = models.SmallIntegerField(
        null=True, blank=True,
        help_text="Original row # in the uploaded Excel file, for traceability during review.",
    )
    validation_status = models.CharField(max_length=20,
                                         choices=ValidationStatus.choices,
                                         default=ValidationStatus.OK)
    status = models.CharField(max_length=15, choices=Status.choices,
                              default=Status.PENDING_INVITE)
    result = models.CharField(max_length=10, choices=Result.choices,
                              default=Result.PENDING)
    overall_score = models.DecimalField(max_digits=5, decimal_places=2,
                                        null=True, blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL,
                                   null=True, db_column='created_by')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        db_table = 'candidates'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['batch', 'status'], name='ix_candidates_batch_status'),
            models.Index(fields=['aadhaar_number'], name='ix_candidates_aadhaar'),
            models.Index(fields=['email'], name='ix_candidates_email'),
            models.Index(fields=['status'], name='ix_candidates_status'),
            models.Index(fields=['result'], name='ix_candidates_result'),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.email})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}" if self.last_name else self.first_name


class DuplicateCheck(models.Model):
    """Result of matching a newly-uploaded candidate's Aadhaar against historical records."""
    class CheckStatus(models.TextChoices):
        NEW = 'new', 'New'
        # Seen before, but never sat the assessment - so the cooling-off window hasn't started.
        # Worth flagging (they may be mid-process in another batch) without blocking anything.
        PREVIOUSLY_INVITED = 'previously_invited', 'Invited Before - Not Attempted'
        DUPLICATE_CLEARED = 'duplicate_cleared', 'Duplicate Cleared'
        DUPLICATE_WITHIN_WINDOW = 'duplicate_within_window', 'Duplicate Within Window'

    check_id = models.BigAutoField(primary_key=True)
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE,
                                  db_column='candidate_id',
                                  related_name='duplicate_checks')
    check_status = models.CharField(max_length=25, choices=CheckStatus.choices,
                                    default=CheckStatus.NEW)
    existing_candidate = models.ForeignKey(Candidate, on_delete=models.SET_NULL,
                                           null=True, db_column='existing_candidate_id',
                                           related_name='duplicate_matches')
    existing_attempt_date = models.DateTimeField(null=True, blank=True)
    cooling_off_months = models.SmallIntegerField(default=3)
    checked_by = models.ForeignKey(User, on_delete=models.SET_NULL,
                                   null=True, db_column='checked_by')
    checked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'duplicate_checks'
        indexes = [
            models.Index(fields=['candidate'], name='ix_dupchecks_candidate'),
        ]

    def __str__(self):
        return f"Check #{self.check_id} - {self.candidate.email}"


class Invitation(models.Model):
    """One row per assessment-link email sent to a candidate."""
    class EmailStatus(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        SENT = 'sent', 'Sent'
        DELIVERED = 'delivered', 'Delivered'
        FAILED = 'failed', 'Failed'

    invitation_id = models.BigAutoField(primary_key=True)
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE,
                                  db_column='candidate_id')
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, db_column='batch_id')
    unique_link_token = models.CharField(max_length=64, unique=True)
    email_status = models.CharField(max_length=10, choices=EmailStatus.choices,
                                    default=EmailStatus.QUEUED)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    link_clicked_at = models.DateTimeField(null=True, blank=True)
    is_link_used = models.BooleanField(default=False)
    link_expired_at = models.DateTimeField()
    is_re_invite = models.BooleanField(default=False)
    sent_by = models.ForeignKey(User, on_delete=models.SET_NULL,
                                null=True, db_column='sent_by')

    class Meta:
        db_table = 'invitations'
        indexes = [
            models.Index(fields=['candidate', 'batch'], name='ix_invitations_candidate'),
        ]
        constraints = [
            models.UniqueConstraint(fields=['unique_link_token'],
                                   name='ux_invitations_token'),
        ]

    def __str__(self):
        return f"Invite #{self.invitation_id} - {self.candidate.email}"