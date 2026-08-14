from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.settings import api_settings

from api.models import User
from api.services.tokens import token_issued_before_password_change


class CustomJWTAuthentication(JWTAuthentication):
    """JWTAuthentication pinned to api.User instead of Django's AUTH_USER_MODEL.

    The app deliberately keeps its own User table separate from
    django.contrib.auth's User (used only for /admin/ staff login), so the
    token's user lookup is redirected here rather than via get_user_model().
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_model = User

    def get_user(self, validated_token):
        """Resolve the token's user, joining `role` into the same query.

        This reimplements the parent rather than calling it so the lookup can `select_related`
        the role: every permission class and most views read `user.role.role_code`, which would
        otherwise lazy-load as a second query on every authenticated request - a full extra
        network round-trip per request against a remote database.
        """
        try:
            user_id = validated_token[api_settings.USER_ID_CLAIM]
        except KeyError:
            raise InvalidToken('Token contained no recognizable user identification')

        try:
            user = self.user_model.objects.select_related('role').get(
                **{api_settings.USER_ID_FIELD: user_id}
            )
        except self.user_model.DoesNotExist:
            raise AuthenticationFailed('User not found', code='user_not_found')

        if not user.is_active:
            raise AuthenticationFailed('User is inactive', code='user_inactive')

        # is_deleted needs its own check so a soft-deleted account's still-live access token
        # stops working immediately rather than lingering for its remaining lifetime.
        if user.is_deleted:
            raise AuthenticationFailed('User not found', code='user_not_found')

        if token_issued_before_password_change(validated_token, user):
            raise AuthenticationFailed(
                'Token no longer valid - password was changed', code='token_stale'
            )

        return user
