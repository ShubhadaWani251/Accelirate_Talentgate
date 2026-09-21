from django.db import models
from django.utils import timezone
from .users import User


class QuestionBankSection(models.Model):
    """One exam section. Rows here are the ONLY definition of what sections exist - an Admin can
    add a new one from Question Bank Management and every screen picks it up.

    This used to be a lookup table shadowing four hardcoded columns on Batch and ExamAttempt
    (logical_questions, quantitative_cutoff, verbal_score...), so a fifth section had nowhere to
    store its question count, its cutoff or a candidate's score in it. Those are now
    BatchSection and AttemptSectionScore rows.
    """
    section_id = models.AutoField(primary_key=True)
    section_name = models.CharField(max_length=60, unique=True)
    section_key = models.CharField(max_length=30, unique=True,
                                   help_text="e.g. 'logical', 'quantitative'")
    description = models.CharField(max_length=255, null=True, blank=True)
    min_required_active = models.SmallIntegerField(default=50,
                                                   help_text="Question Bank Health threshold")
    # The order candidates sit the sections in, and the order every table's columns appear in.
    # An explicit number rather than alphabetical or creation order: the original four have a
    # deliberate sequence (logical, quantitative, verbal, programming) that neither of those
    # reproduces, and a new section should be placeable inside it rather than only at the end.
    display_order = models.SmallIntegerField(default=100)
    # Retires a section from NEW batches without touching the ones that already used it. A
    # section is never deleted once any batch has referenced it - BatchSection/AttemptSectionScore
    # protect the row - because deleting it would erase what those candidates were actually
    # asked and scored on.
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'question_bank_sections'
        ordering = ['display_order', 'section_name']

    def __str__(self):
        return self.section_name


class Question(models.Model):
    """One row per MCQ."""
    class Difficulty(models.TextChoices):
        EASY = 'Easy', 'Easy'
        MEDIUM = 'Medium', 'Medium'
        HARD = 'Hard', 'Hard'

    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    question_id = models.BigAutoField(primary_key=True)
    question_code = models.CharField(max_length=20, unique=True,
                                     help_text="Display code, e.g. Q-0181")
    section = models.ForeignKey(QuestionBankSection, on_delete=models.PROTECT,
                                db_column='section_id')
    question_text = models.TextField()
    option_a = models.CharField(max_length=500)
    option_b = models.CharField(max_length=500)
    option_c = models.CharField(max_length=500, null=True, blank=True)
    option_d = models.CharField(max_length=500, null=True, blank=True)
    correct_option = models.CharField(max_length=1,
                                      choices=[('A', 'A'), ('B', 'B'),
                                              ('C', 'C'), ('D', 'D')])
    difficulty = models.CharField(max_length=10, choices=Difficulty.choices)
    marks = models.SmallIntegerField(default=1)
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.ACTIVE)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL,
                                   null=True, db_column='created_by')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'questions'
        ordering = ['question_code']
        indexes = [
            models.Index(fields=['section', 'status', 'difficulty'],
                        name='ix_questions_section_status'),
        ]

    def __str__(self):
        return self.question_code