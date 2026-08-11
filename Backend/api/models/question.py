from django.db import models
from django.utils import timezone
from .users import User


class QuestionBankSection(models.Model):
    """Lookup table for exam sections."""
    section_id = models.AutoField(primary_key=True)
    section_name = models.CharField(max_length=60, unique=True)
    section_key = models.CharField(max_length=30, unique=True,
                                   help_text="e.g. 'logical', 'quantitative'")
    description = models.CharField(max_length=255, null=True, blank=True)
    min_required_active = models.SmallIntegerField(default=50,
                                                   help_text="Question Bank Health threshold")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'question_bank_sections'
        ordering = ['section_name']

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