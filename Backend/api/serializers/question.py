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
    # True once any batch has used this section. The UI needs it to explain why a section can be
    # retired but not deleted - the batches that used it, and the candidates scored under it,
    # are what stop it going away.
    in_use = serializers.SerializerMethodField()

    class Meta:
        model = QuestionBankSection
        fields = [
            'section_id', 'section_name', 'section_key', 'min_required_active',
            'display_order', 'is_active', 'in_use',
            'total_questions', 'active_questions', 'inactive_questions',
        ]
        # section_key is DERIVED from the name on create (see SectionCreateSerializer) and is
        # never editable afterwards: it is the stable identifier every score row, filter param
        # and export column is keyed on, so renaming it would orphan all of them. The display
        # NAME stays editable.
        read_only_fields = ['section_id', 'section_key']

    def get_in_use(self, section):
        return section.batch_sections.exists()


class SectionCreateSerializer(serializers.ModelSerializer):
    """Creating a section from Question Bank Management.

    Only a name is required. section_key is generated from it rather than asked for: it is an
    internal identifier an Admin has no reason to choose, and letting one be typed invites a key
    that collides with an existing one or contains characters the query params and export
    columns keyed on it cannot carry.
    """

    class Meta:
        model = QuestionBankSection
        fields = ['section_name', 'description', 'min_required_active', 'display_order']

    def validate_section_name(self, value):
        value = ' '.join((value or '').split())
        if not value:
            raise serializers.ValidationError('A section name is required.')
        if QuestionBankSection.objects.filter(section_name__iexact=value).exists():
            raise serializers.ValidationError('A section with this name already exists.')
        if not _section_key_from_name(value):
            raise serializers.ValidationError(
                'The name must contain at least one letter or number.'
            )
        return value

    def create(self, validated_data):
        validated_data['section_key'] = _unique_section_key(validated_data['section_name'])
        return super().create(validated_data)


def _section_key_from_name(name):
    """A lowercase, underscore-separated key from a display name: 'Data Interpretation' ->
    'data_interpretation'. Restricted to [a-z0-9_] because this value becomes a query-parameter
    name (`<key>_min`) and a dict key in the API's per-section score map.
    """
    return re.sub(r'[^a-z0-9]+', '_', (name or '').lower()).strip('_')[:30]


def _unique_section_key(name):
    """`_section_key_from_name`, suffixed if that key is taken.

    Two different display names can reduce to the same key ('Data Interpretation' and
    'Data-Interpretation'), and section_key is unique - without this the second create would
    fail with a database integrity error instead of simply getting its own key.
    """
    base = _section_key_from_name(name)
    key, suffix = base, 2
    while QuestionBankSection.objects.filter(section_key=key).exists():
        tail = f'_{suffix}'
        key = f'{base[:30 - len(tail)]}{tail}'
        suffix += 1
    return key


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
