import re

from rest_framework import serializers

from api.models import Question, QuestionBankSection


def normalize_question_text(text):
    """Comparison key for duplicate detection: case-folded with runs of whitespace collapsed.

    Two questions that differ only in capitalisation, indentation, or a stray double space are
    the same question to a candidate, so they're the same question to the bank.
    """
    return re.sub(r'\s+', ' ', (text or '')).strip().lower()


def find_duplicate_question(text, exclude_pk=None):
    """Return an existing Question with the same normalised text, or None.

    Deliberately bank-wide rather than per-section: the same question filed under two sections
    is still a duplicate (and usually means one of them was mis-filed). Inactive questions
    count too - the text still exists in the bank and could be reactivated.

    Filters in Python because the normalisation (whitespace collapsing) has no SQL equivalent
    that could use an index; the bank is a few hundred rows, so one scan is cheaper than the
    machinery to maintain a normalised column.
    """
    target = normalize_question_text(text)
    if not target:
        return None
    qs = Question.objects.all()
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    for question_id, existing_text, code in qs.values_list('question_id', 'question_text', 'question_code'):
        if normalize_question_text(existing_text) == target:
            return {'question_id': question_id, 'question_code': code}
    return None


class QuestionBankSectionSerializer(serializers.ModelSerializer):
    """A section, plus its question counts when the view annotated them.

    The three counts default to None rather than 0 when absent, so a caller that forgot to
    annotate is visibly missing data instead of silently reporting every section as empty.
    """
    total_questions = serializers.IntegerField(read_only=True, default=None)
    active_questions = serializers.IntegerField(read_only=True, default=None)
    inactive_questions = serializers.IntegerField(read_only=True, default=None)

    class Meta:
        model = QuestionBankSection
        fields = [
            'section_id', 'section_name', 'section_key', 'min_required_active',
            'total_questions', 'active_questions', 'inactive_questions',
        ]


class QuestionSerializer(serializers.ModelSerializer):
    """Used for both create (Add Question) and edit (Edit Question modal)."""
    section_name = serializers.CharField(source='section.section_name', read_only=True)
    section_key = serializers.CharField(source='section.section_key', read_only=True)
    # Annotated by QuestionListCreateView.get only. A create/update response serializes a bare
    # model instance with no annotation, so this must tolerate its absence rather than raising.
    section_number = serializers.IntegerField(read_only=True, default=None)
    difficulty_display = serializers.CharField(source='get_difficulty_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Question
        fields = [
            'question_id', 'question_code', 'section_number', 'section', 'section_name',
            'section_key',
            'question_text', 'option_a', 'option_b', 'option_c', 'option_d', 'correct_option',
            'difficulty', 'difficulty_display', 'marks', 'status', 'status_display',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'question_id', 'question_code', 'section_number', 'created_at', 'updated_at',
        ]

    def validate_question_text(self, value):
        duplicate = find_duplicate_question(
            value, exclude_pk=self.instance.pk if self.instance else None,
        )
        if duplicate:
            raise serializers.ValidationError(
                f'This question already exists in the bank as {duplicate["question_code"]}.'
            )
        return value

    def validate(self, attrs):
        option_c = attrs.get('option_c', getattr(self.instance, 'option_c', None))
        option_d = attrs.get('option_d', getattr(self.instance, 'option_d', None))
        correct_option = attrs.get('correct_option', getattr(self.instance, 'correct_option', None))
        if correct_option == 'C' and not option_c:
            raise serializers.ValidationError({'correct_option': 'Option C is empty.'})
        if correct_option == 'D' and not option_d:
            raise serializers.ValidationError({'correct_option': 'Option D is empty.'})
        return attrs

    def create(self, validated_data):
        validated_data['question_code'] = generate_question_code()
        return super().create(validated_data)


def generate_question_code():
    """Q-0001, Q-0002, ... - based on the highest existing numeric suffix rather than row
    count, so a deleted/renumbered row never causes a collision. Re-queries the DB on every
    call (rather than caching), so repeated calls within the same bulk-import transaction
    correctly see rows created earlier in that same transaction.
    """
    last = Question.objects.order_by('-question_id').values_list('question_code', flat=True).first()
    next_number = 1
    if last and last.startswith('Q-'):
        try:
            next_number = int(last.split('-', 1)[1]) + 1
        except ValueError:
            next_number = Question.objects.count() + 1
    return f'Q-{next_number:04d}'
