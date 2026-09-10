from rest_framework import serializers

from api.services.exam_session import TERMINATION_MESSAGES


class EmailVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()


class TerminateSerializer(serializers.Serializer):
    # Omitted/unrecognized falls back to TAB_SWITCH in the view - the most common real cause -
    # rather than rejecting the request outright, since the exam still needs to end either way.
    reason = serializers.ChoiceField(choices=list(TERMINATION_MESSAGES), required=False)
    # Only ever sent alongside forbidden_object_detected. Explicitly typed rather than a raw
    # JSONField so a candidate's browser can't smuggle arbitrary keys into ProctoringEvent's
    # stored event_details.
    detected_object = serializers.CharField(required=False, max_length=40)
    confidence = serializers.FloatField(required=False, min_value=0, max_value=1)


class AnswerSerializer(serializers.Serializer):
    # Blank/null clears a previously-selected answer (candidate changed their mind) - the model
    # field itself is nullable for exactly this reason.
    selected_option = serializers.ChoiceField(
        choices=['A', 'B', 'C', 'D'], required=False, allow_null=True, allow_blank=True,
    )
    time_spent_seconds = serializers.IntegerField(required=False, min_value=0)
    # Omitted means "don't touch" (see exam_session.save_answer) - a plain answer-select must
    # not silently clear an existing review flag, and a review-only toggle must not require
    # resending whatever option is currently selected.
    marked_for_review = serializers.BooleanField(required=False)
