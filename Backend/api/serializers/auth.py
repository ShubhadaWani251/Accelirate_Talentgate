from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from api.models import User
from api.services.passwords import is_password_reused

# Applied to every raw password field. Not a "your password can't be longer than this"
# UX rule - it's a cap so an oversized payload can't be used to run up hashing cost
# (PBKDF2 cost scales with input size) as a lightweight DoS vector.
MAX_PASSWORD_LENGTH = 128


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True, max_length=MAX_PASSWORD_LENGTH, style={'input_type': 'password'}
    )


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ResendOtpSerializer(serializers.Serializer):
    email = serializers.EmailField()


class VerifyOtpResetSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(min_length=6, max_length=6)
    new_password = serializers.CharField(write_only=True, max_length=MAX_PASSWORD_LENGTH)
    confirm_password = serializers.CharField(write_only=True, max_length=MAX_PASSWORD_LENGTH)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        try:
            validate_password(attrs['new_password'])
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'new_password': list(exc.messages)})
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, max_length=MAX_PASSWORD_LENGTH)
    new_password = serializers.CharField(write_only=True, max_length=MAX_PASSWORD_LENGTH)
    confirm_password = serializers.CharField(write_only=True, max_length=MAX_PASSWORD_LENGTH)

    def validate(self, attrs):
        user = self.context['request'].user
        if not user.check_password(attrs['current_password']):
            raise serializers.ValidationError({'current_password': 'Current password is incorrect.'})
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        try:
            validate_password(attrs['new_password'], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'new_password': list(exc.messages)})
        # Safe to check reuse here (unlike the OTP-reset flow) - this endpoint requires an
        # already-authenticated request, so there's no OTP-guessing oracle to worry about.
        if is_password_reused(user, attrs['new_password']):
            raise serializers.ValidationError({
                'new_password': f'Cannot reuse your current password or your last '
                                 f'{settings.PASSWORD_HISTORY_COUNT} passwords.'
            })
        return attrs


class UserProfileSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source='role.role_name', read_only=True)
    role_code = serializers.CharField(source='role.role_code', read_only=True)

    class Meta:
        model = User
        fields = [
            'user_id', 'first_name', 'last_name', 'email', 'phone',
            'role_name', 'role_code', 'is_active', 'last_login_at',
        ]
        read_only_fields = fields
