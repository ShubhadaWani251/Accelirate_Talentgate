from rest_framework import serializers

from api.models import Question, QuestionBankSection


class QuestionBankSectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionBankSection
        fields = ['section_id', 'section_name', 'section_key', 'min_required_active']


class QuestionSerializer(serializers.ModelSerializer):
    """Used for both create (Add Question) and edit (Edit Question modal)."""
    section_name = serializers.CharField(source='section.section_name', read_only=True)
    section_key = serializers.CharField(source='section.section_key', read_only=True)
    difficulty_display = serializers.CharField(source='get_difficulty_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Question
        fields = [
            'question_id', 'question_code', 'section', 'section_name', 'section_key',
            'question_text', 'option_a', 'option_b', 'option_c', 'option_d', 'correct_option',
            'difficulty', 'difficulty_display', 'marks', 'status', 'status_display',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['question_id', 'question_code', 'created_at', 'updated_at']

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
