from django.db import models
from django.utils import timezone
from .candidate import Candidate, Invitation
from .question import Question


class ExamAttempt(models.Model):
    """One row per exam attempt with identity verification and proctoring.

    is_authenticated/is_anonymous are provided so DRF's IsAuthenticated permission (which reads
    request.user.is_authenticated) works when request.user is an ExamAttempt - see
    api.authentication.CandidateAttemptAuthentication, which resolves a candidate's exam JWT
    to an instance of this model instead of a User, the same way api.models.User does it for
    staff logins.
    """
    is_authenticated = True
    is_anonymous = False

    class Status(models.TextChoices):
        IN_PROGRESS = 'in_progress', 'In Progress'
        SUBMITTED = 'submitted', 'Submitted'
        TERMINATED = 'terminated', 'Terminated'

    attempt_id = models.BigAutoField(primary_key=True)
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE,
                                  db_column='candidate_id')
    invitation = models.ForeignKey(Invitation, on_delete=models.CASCADE,
                                   db_column='invitation_id')

    # Identity verification
    aadhaar_capture_url = models.URLField(max_length=500, null=True, blank=True)
    face_photo_url = models.URLField(max_length=500, null=True, blank=True)
    face_match_confidence = models.DecimalField(max_digits=5, decimal_places=2,
                                                null=True, blank=True)
    id_verified_at = models.DateTimeField(null=True, blank=True)
    session_recording_url = models.URLField(max_length=500, null=True, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    terminated_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices,
                              default=Status.IN_PROGRESS)
    termination_reason = models.CharField(max_length=255, null=True, blank=True)

    # Scores
    total_answered = models.SmallIntegerField(default=0)
    total_correct = models.SmallIntegerField(default=0)
    overall_score = models.DecimalField(max_digits=5, decimal_places=2,
                                        null=True, blank=True)
    logical_score = models.SmallIntegerField(null=True, blank=True)
    quantitative_score = models.SmallIntegerField(null=True, blank=True)
    verbal_score = models.SmallIntegerField(null=True, blank=True)
    programming_score = models.SmallIntegerField(null=True, blank=True)

    # Section pass/fail
    logical_cleared = models.BooleanField(null=True, blank=True)
    quantitative_cleared = models.BooleanField(null=True, blank=True)
    verbal_cleared = models.BooleanField(null=True, blank=True)
    programming_cleared = models.BooleanField(null=True, blank=True)

    # Metadata
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    user_agent = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = 'exam_attempts'
        indexes = [
            models.Index(fields=['candidate'], name='ix_attempts_candidate'),
        ]
        constraints = [
            models.UniqueConstraint(fields=['invitation'],
                                   name='ux_attempts_invitation')
        ]

    def __str__(self):
        return f"Attempt #{self.attempt_id} - {self.candidate.email}"


class ExamAnswer(models.Model):
    """One row per question answered in an exam."""
    answer_id = models.BigAutoField(primary_key=True)
    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE,
                                db_column='attempt_id')
    question = models.ForeignKey(Question, on_delete=models.PROTECT,
                                 db_column='question_id')
    selected_option = models.CharField(max_length=1, null=True, blank=True,
                                       choices=[('A', 'A'), ('B', 'B'),
                                               ('C', 'C'), ('D', 'D')])
    is_correct = models.BooleanField(null=True, blank=True)
    time_spent_seconds = models.SmallIntegerField(null=True, blank=True)
    is_auto_saved = models.BooleanField(default=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    # Independent of selected_option - a candidate can flag a question for a second pass whether
    # or not they've answered it yet, and answering it doesn't clear the flag (only an explicit
    # unmark does). See services/exam_session.save_answer / set_marked_for_review.
    marked_for_review = models.BooleanField(default=False)

    class Meta:
        db_table = 'exam_answers'
        constraints = [
            models.UniqueConstraint(fields=['attempt', 'question'],
                                   name='ux_answers_attempt_question')
        ]

    def __str__(self):
        return f"Answer #{self.answer_id} - Q{self.question.question_id}"


class ProctoringEvent(models.Model):
    """Fine-grained event stream during an exam attempt."""
    class Severity(models.TextChoices):
        INFO = 'info', 'Info'
        WARNING = 'warning', 'Warning'
        CRITICAL = 'critical', 'Critical'

    event_id = models.BigAutoField(primary_key=True)
    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE,
                                db_column='attempt_id')
    event_type = models.CharField(max_length=40,
                                  help_text="e.g. session_start, tab_switch")
    event_details = models.JSONField(null=True, blank=True)
    is_violation = models.BooleanField(default=False)
    severity = models.CharField(max_length=10, choices=Severity.choices,
                                default=Severity.INFO)
    event_timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'proctoring_events'
        indexes = [
            models.Index(fields=['attempt', 'event_timestamp'],
                        name='ix_events_attempt'),
        ]

    def __str__(self):
        return f"Event #{self.event_id} - {self.event_type}"