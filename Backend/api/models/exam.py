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
    # An MP4 copy of the same recording, produced by services.video_transcode once the attempt
    # is SUBMITTED/TERMINATED (never while IN_PROGRESS - the WebM append blob is still being
    # written to until then). Null until transcoded, same convention as every other "did X
    # happen yet" field on this model. mp4_transcode_attempts caps automatic retries on a
    # recording that keeps failing to convert (a genuinely corrupt upload, say) - see
    # management/commands/transcode_recordings.py's own MAX_TRANSCODE_ATTEMPTS - so a permanently
    # broken file does not burn CPU on every scheduled tick forever.
    session_recording_mp4_url = models.URLField(max_length=500, null=True, blank=True)
    mp4_transcode_attempts = models.SmallIntegerField(default=0)

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
    # Set the first time a request for this attempt carries a verified SEB Browser Exam Key
    # header (see services/seb.record_seb_usage) - never cleared once set, and never required:
    # SEB is a strong default, not a gate, so a candidate who falls back to a regular browser
    # simply leaves this null rather than being blocked. A timestamp, not a boolean, to match
    # every other "did X happen" fact on this model (id_verified_at, started_at, and so on).
    seb_verified_at = models.DateTimeField(null=True, blank=True)
    # Stamped on every successful CandidateAttemptAuthentication check (see authentication.py) -
    # the recording-chunk upload alone already updates this roughly every 10s for as long as the
    # candidate's browser/SEB is genuinely still open and running, so this doubles as a
    # heartbeat: management/commands/terminate_stale_attempts.py watches for it going quiet
    # while an attempt is still IN_PROGRESS and within its own time budget, which is what a
    # closed browser/SEB process looks like from the server's side (nothing can "phone home"
    # after the process is gone - there is no JS event that survives that). A page refresh also
    # stops this briefly, which is why the command's staleness threshold is generous compared to
    # an ordinary reload's few seconds.
    last_activity_at = models.DateTimeField(null=True, blank=True)

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