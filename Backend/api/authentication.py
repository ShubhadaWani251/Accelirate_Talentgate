from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

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
        user = super().get_user(validated_token)

        # Parent already checks is_active; is_deleted needs its own check so a
        # soft-deleted account's still-live access token stops working immediately
        # rather than lingering for up to its remaining lifetime.
        if user.is_deleted:
            raise AuthenticationFailed('User not found', code='user_not_found')

        if token_issued_before_password_change(validated_token, user):
            raise AuthenticationFailed(
                'Token no longer valid - password was changed', code='token_stale'
            )

        return user
