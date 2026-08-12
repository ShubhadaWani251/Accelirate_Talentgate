from rest_framework import serializers

from api.models import Role, User
from api.utils.validation import is_corporate_email

VALID_ROLE_CODES = ('admin', 'ta')


class UserListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    role_name = serializers.CharField(source='role.role_name', read_only=True)
    role_code = serializers.CharField(source='role.role_code', read_only=True)

    class Meta:
        model = User
        fields = ['user_id', 'full_name', 'email', 'role_name', 'role_code', 'is_active']


class AssignedBatchSerializer(serializers.Serializer):
    batch_id = serializers.IntegerField()
    batch_name = serializers.CharField()
    college_name = serializers.CharField()
    total_candidates = serializers.IntegerField()
    status = serializers.CharField()
    status_display = serializers.CharField()


class UserDetailSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    role_name = serializers.CharField(source='role.role_name', read_only=True)
    role_code = serializers.CharField(source='role.role_code', read_only=True)
    assigned_batches = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'user_id', 'first_name', 'last_name', 'full_name', 'email',
            'role', 'role_name', 'role_code', 'is_active', 'assigned_batches',
        ]
        read_only_fields = ['user_id', 'role_name', 'role_code', 'assigned_batches']

    def get_assigned_batches(self, user):
        batches = user.primary_batches.filter(is_deleted=False).order_by('-created_at')
        return AssignedBatchSerializer([
            {
                'batch_id': b.batch_id,
                'batch_name': b.batch_name,
                'college_name': b.college_name,
                'total_candidates': b.total_candidates,
                'status': b.status,
                'status_display': b.get_status_display(),
            }
            for b in batches
        ], many=True).data


class UserCreateSerializer(serializers.Serializer):
    """Add User form - Name, Corporate Email, Role. No password field (see
    services/user_provisioning.py for how credentials reach the new user).
    """
    first_name = serializers.CharField(max_length=80)
    last_name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    email = serializers.EmailField(max_length=150)
    role = serializers.ChoiceField(choices=VALID_ROLE_CODES)

    def validate_email(self, value):
        value = value.strip().lower()
        if not is_corporate_email(value):
            raise serializers.ValidationError('Must be a corporate email address.')
        if User.objects.filter(email__iexact=value, is_deleted=False).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate_role(self, value):
        try:
            return Role.objects.get(role_code=value)
        except Role.DoesNotExist:
            raise serializers.ValidationError('Invalid role.')


class UserUpdateSerializer(serializers.Serializer):
    """Edit User Access screen - name, role, active status. Email is not editable here
    (it's the account's login identity, and changing it has no verification flow designed
    in the wireframe)."""
    first_name = serializers.CharField(max_length=80, required=False)
    last_name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=VALID_ROLE_CODES, required=False)
    is_active = serializers.BooleanField(required=False)

    def validate_role(self, value):
        try:
            return Role.objects.get(role_code=value)
        except Role.DoesNotExist:
            raise serializers.ValidationError('Invalid role.')
