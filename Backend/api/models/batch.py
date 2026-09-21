from django.db import models
from django.utils import timezone
from .question import QuestionBankSection
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
    # Optional at the batch level: each candidate already carries their own college_name from the
    # upload sheet (a batch can be a mixed drive), so this was often redundant with what candidate
    # rows already record.
    college_name = models.CharField(max_length=150, null=True, blank=True)
    # Nullable: a batch is created from just its name and college (see BatchListCreateView.post)
    # and doesn't have an assessment window yet - that's set on the "Review & Send Invite" step,
    # immediately before the invite goes out. Never null once a batch has ever had invites sent.
    link_valid_from = models.DateTimeField(null=True, blank=True)
    link_valid_until = models.DateTimeField(null=True, blank=True)

    # Exam configuration.
    #
    # Which sections this batch uses, and how many questions and what cutoff each one gets, live
    # in BatchSection rows below - NOT here. The eight columns that follow are DEPRECATED: they
    # are the pre-BatchSection storage, kept only so migration 0035's backfill has a source and
    # so a rollback has somewhere to land. Nothing reads them any more; read `batch.sections`.
    # They are dropped in a separate, later migration once this has run cleanly in production.
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
    # Client-side AI proctoring (face count, forbidden-object detection, voice activity - see
    # exam_session.WARNABLE_REASONS) is on by default. Off means the two guard hooks never
    # activate for this batch's candidates at all, not just that violations are ignored -
    # see ExamAttemptPage.jsx, which ANDs this into the hooks' own `active` argument.
    ai_proctoring_enabled = models.BooleanField(default=True)

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


class BatchSection(models.Model):
    """One row per section a batch actually uses, with that batch's own question count and
    cutoff for it.

    Replaces Batch's eight `<section>_questions`/`<section>_cutoff` columns. Those could only
    ever describe the four sections someone had written columns for; a batch that wants three
    sections, or five, or a newly added one, has no way to say so in a fixed set of columns.

    Rows are a SNAPSHOT taken when the batch is created (from the org-wide defaults) and are
    frozen once the batch leaves Draft, exactly as the columns were - the cutoff stays editable
    afterwards so a TA can revise it against a scored cohort, and that is the only field that
    does. Changing the org defaults never reaches an existing batch.
    """
    batch_section_id = models.BigAutoField(primary_key=True)
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, db_column='batch_id',
                              related_name='sections')
    # PROTECT, not CASCADE: a section that any batch has ever used must not be deletable, or the
    # deletion silently rewrites what those candidates were assessed on. Retiring a section is
    # QuestionBankSection.is_active instead.
    section = models.ForeignKey(QuestionBankSection, on_delete=models.PROTECT,
                                db_column='section_id', related_name='batch_sections')
    question_count = models.SmallIntegerField(default=10)
    cutoff = models.DecimalField(max_digits=5, decimal_places=2, default=70.00)

    class Meta:
        db_table = 'batch_sections'
        # Candidates sit sections in this order and every table renders its columns in it, so it
        # is defined once here rather than by each caller remembering to sort.
        ordering = ['section__display_order', 'section__section_name']
        constraints = [
            models.UniqueConstraint(fields=['batch', 'section'],
                                    name='ux_batch_sections_batch_section'),
        ]

    def __str__(self):
        return f'{self.batch.batch_name} - {self.section.section_name}'
