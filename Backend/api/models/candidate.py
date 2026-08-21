from django.db import models
from django.utils import timezone
from .users import User
from .batch import Batch


class Candidate(models.Model):
    """One row per candidate profile within a batch."""
    class ValidationStatus(models.TextChoices):
        """Headline verdict for one uploaded row.

        A row can fail several checks at once (no name AND a malformed email AND a repeated
        address); this field carries only the FIRST one, for the status pill and for the
        `!= OK` gate that blocks finalizing. The full list lives in `validation_errors`.
        """
        OK = 'ok', 'OK'
        MISSING_EMAIL = 'missing_email', 'Missing Email'
        MISSING_AADHAAR = 'missing_aadhaar', 'Missing Aadhaar Last 4 Digits'
        MISSING_NAME = 'missing_name', 'Missing Name'
        MISSING_COLLEGE = 'missing_college', 'Missing College'
        INVALID_EMAIL = 'invalid_email', 'Invalid Email'
        DUPLICATE_EMAIL = 'duplicate_email', 'Duplicate Email'
        INVALID_AADHAAR = 'invalid_aadhaar', 'Invalid Aadhaar Last 4 Digits'
        DUPLICATE_AADHAAR = 'duplicate_aadhaar', 'Duplicate Aadhaar Last 4 Digits'
        INVALID_MOBILE = 'invalid_mobile', 'Invalid Mobile'
        INVALID_TEXT = 'invalid_text', 'Invalid Text Field'
        INVALID_PERCENTAGE = 'invalid_percentage', 'Invalid Percentage'
        INVALID_YEAR = 'invalid_year', 'Invalid Passing Year'
        MISSING_MOBILE = 'missing_mobile', 'Missing Mobile'
        MISSING_DEGREE = 'missing_degree', 'Missing Degree'
        MISSING_STREAM = 'missing_stream', 'Missing Stream'
        MISSING_PERCENTAGE = 'missing_percentage', 'Missing Percentage'
        MISSING_YEAR = 'missing_year', 'Missing Passing Out Year'
        MISSING_LOCATION = 'missing_location', 'Missing Location'

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
    # Only the last four digits are ever stored. A full Aadhaar number is sensitive identity
    # data the platform has no use for: it existed purely as a duplicate-detection key, and
    # that job is now done by (last four + name) - see services/duplicate_check.py. Four digits
    # alone collide often (10,000 possible values), which is exactly why the name is part of
    # the key rather than this field being trusted on its own.
    aadhaar_last4 = models.CharField(
        max_length=4,
        help_text="Last 4 digits of the candidate's Aadhaar number. The full number is never "
                  "stored.",
    )

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
    validation_errors = models.JSONField(
        default=list, blank=True,
        help_text="Every problem found with this uploaded row: "
                  "[{'field': 'Email', 'message': '...'}, ...]. Empty when the row is valid. "
                  "Stored rather than recomputed so the review screen and the finalize check "
                  "can never disagree about why a row was rejected.",
    )
    upload_raw = models.JSONField(
        default=dict, blank=True,
        help_text="Original spreadsheet text for fields whose model type can't hold a bad "
                  "value: a Percentage cell reading 'abc' parses to NULL, making it "
                  "indistinguishable from an empty cell, so 'must be a number' could never be "
                  "reported. Keyed by field name, e.g. {'percentage': 'abc'}.",
    )
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
            models.Index(fields=['aadhaar_last4'], name='ix_candidates_aadhaar'),
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
        """Labels match the wireframe's Upload Review wording, and each maps to one colour:
        green = safe to invite, amber = worth a look, red = needs a decision.
        """
        NEW = 'new', 'New Candidate'
        # Seen before, but never sat the assessment - so the cooling-off window hasn't started.
        # Worth flagging (they may be mid-process in another batch) without blocking anything.
        PREVIOUSLY_INVITED = 'previously_invited', 'Invited Before - Not Attempted'
        DUPLICATE_CLEARED = 'duplicate_cleared', 'Duplicate Found - Cleared'
        DUPLICATE_WITHIN_WINDOW = 'duplicate_within_window', 'Duplicate Found - Within Window'

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
    # Why the send failed, when it did. Previously the exception went only to the application
    # log, so the UI could say FAILED without anyone being able to find out why - and the
    # common causes (an unverified sender, a mistyped address, a timeout) need completely
    # different fixes. Cleared on a successful send so a stale reason can't linger next to a
    # SENT status.
    email_error = models.TextField(
        null=True, blank=True,
        help_text="Error reported by the email service on the last failed attempt. Null when "
                  "the last attempt succeeded.",
    )
    # When the last send was ATTEMPTED, successful or not. email_sent_at only moves on success,
    # so without this a repeatedly-failing invitation looks like nothing was ever tried.
    email_last_attempt_at = models.DateTimeField(null=True, blank=True)
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