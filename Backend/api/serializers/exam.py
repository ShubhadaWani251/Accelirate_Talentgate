from rest_framework import serializers

from api.services.exam_session import TERMINATION_MESSAGES


class EmailVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()


class TerminateSerializer(serializers.Serializer):
    # Omitted/unrecognized falls back to TAB_SWITCH in the view - the most common real cause -
    # rather than rejecting the request outright, since the exam still needs to end either way.
    reason = serializers.ChoiceField(choices=list(TERMINATION_MESSAGES), required=False)


class AnswerSerializer(serializers.Serializer):
    # Blank/null clears a previously-selected answer (candidate changed their mind) - the model
    # field itself is nullable for exactly this reason.
    selected_option = serializers.ChoiceField(
        choices=['A', 'B', 'C', 'D'], required=False, allow_null=True, allow_blank=True,
    )
    time_spent_seconds = serializers.IntegerField(required=False, min_value=0)
