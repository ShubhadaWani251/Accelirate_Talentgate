from django.conf import settings
from django.contrib.auth.hashers import check_password as check_hash, make_password
from django.utils import timezone
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError

from api.models import AuditLog, OTPVerification, User
from api.serializers.auth import (
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    LoginSerializer,
    ResendOtpSerializer,
    UserProfileSerializer,
    VerifyOtpResetSerializer,
)
from api.services.lockout import clear_failed_attempts, is_locked_out, register_failed_attempt
from api.services.otp import OtpCooldownError, issue_otp
from api.services.passwords import is_password_reused, record_password_history
from api.services.tokens import issue_tokens_for_user, revoke_refresh_token, rotate_refresh_token
from api.utils.net import get_client_ip, ratelimit_ip_key
from api.utils.validation import is_corporate_email

# A dummy hash to run password verification against when no matching user exists, so a
# nonexistent email doesn't return measurably faster than one that requires an actual
# check_password() call - the same mitigation Django's own ModelBackend uses.
_DUMMY_PASSWORD_HASH = make_password('not-a-real-password-just-for-timing')


def _user_agent(request):
    return request.META.get('HTTP_USER_AGENT', '')[:255]


def _log(request, user, action_type, entity_id=None):
    AuditLog.objects.create(
        user=user,
        action_type=action_type,
        entity_type='user',
        entity_id=entity_id if entity_id is not None else (user.user_id if user else 0),
        ip_address=get_client_ip(request),
        user_agent=_user_agent(request),
    )


def _set_refresh_cookie(response, refresh_token):
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds()),
        path=settings.REFRESH_COOKIE_PATH,
        httponly=True,
        secure=not settings.DEBUG,
        samesite='Strict',
    )


def _clear_refresh_cookie(response):
    response.delete_cookie(key=settings.REFRESH_COOKIE_NAME, path=settings.REFRESH_COOKIE_PATH)


@method_decorator(ratelimit(key=ratelimit_ip_key, rate='10/m', method='POST', block=False), name='post')
class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if getattr(request, 'limited', False):
            return Response({'detail': 'Too many login attempts. Please try again shortly.'},
                             status=status.HTTP_429_TOO_MANY_REQUESTS)

        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        password = serializer.validated_data['password']

        generic_error = {'detail': 'Invalid email or password.'}

        if is_locked_out(email):
            return Response({'detail': 'Too many failed attempts. Please try again later.'},
                             status=status.HTTP_429_TOO_MANY_REQUESTS)

        if not is_corporate_email(email):
            check_hash(password, _DUMMY_PASSWORD_HASH)  # keep timing consistent with the checks below
            register_failed_attempt(email)
            return Response(generic_error, status=status.HTTP_401_UNAUTHORIZED)

        try:
            user = User.objects.select_related('role').get(
                email__iexact=email, is_deleted=False,
            )
        except User.DoesNotExist:
            check_hash(password, _DUMMY_PASSWORD_HASH)  # see _DUMMY_PASSWORD_HASH docstring
            register_failed_attempt(email)
            return Response(generic_error, status=status.HTTP_401_UNAUTHORIZED)

        if not user.is_active or not user.check_password(password):
            register_failed_attempt(email)
            if user.is_active:  # only log against a real, active account
                _log(request, user, 'login_failed')
            return Response(generic_error, status=status.HTTP_401_UNAUTHORIZED)

        clear_failed_attempts(email)
        refresh_token, access_token = issue_tokens_for_user(user)
        user.last_login_at = timezone.now()
        user.save(update_fields=['last_login_at'])
        _log(request, user, 'login')

        response = Response({
            'access_token': access_token,
            'user': UserProfileSerializer(user).data,
        })
        _set_refresh_cookie(response, refresh_token)
        return response


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw_refresh = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if raw_refresh:
            revoke_refresh_token(raw_refresh)
        _log(request, request.user, 'logout')
        response = Response({'detail': 'Logged out.'})
        _clear_refresh_cookie(response)
        return response


class RefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        raw_refresh = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if not raw_refresh:
            return Response({'detail': 'No refresh token.'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            (new_refresh, new_access), user = rotate_refresh_token(raw_refresh)
        except TokenError:
            response = Response({'detail': 'Session expired. Please log in again.'},
                                 status=status.HTTP_401_UNAUTHORIZED)
            _clear_refresh_cookie(response)
            return response

        response = Response({
            'access_token': new_access,
            'user': UserProfileSerializer(user).data,
        })
        _set_refresh_cookie(response, new_refresh)
        return response


@method_decorator(ratelimit(key=ratelimit_ip_key, rate='5/m', method='POST', block=False), name='post')
class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if getattr(request, 'limited', False):
            return Response({'detail': 'Too many requests. Please try again shortly.'},
                             status=status.HTTP_429_TOO_MANY_REQUESTS)

        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        # Explicitly reveals whether the email is registered (per product decision) rather
        # than the previous anti-enumeration generic response - anyone relying on the old
        # "no enumeration" guarantee should know this endpoint no longer provides it.
        not_found_response = Response(
            {'detail': 'No account found for this email address.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

        if not is_corporate_email(email):
            return not_found_response

        try:
            user = User.objects.get(email__iexact=email, is_active=True, is_deleted=False)
        except User.DoesNotExist:
            return not_found_response

        try:
            issue_otp(user, async_send=True)
        except OtpCooldownError as exc:
            return Response(
                {'detail': f'Please wait {exc.retry_after_seconds}s before requesting another code.',
                 'retry_after_seconds': exc.retry_after_seconds},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        return Response({'detail': 'A reset code has been sent to your email.'})


@method_decorator(ratelimit(key=ratelimit_ip_key, rate='5/m', method='POST', block=False), name='post')
class ResendOtpView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if getattr(request, 'limited', False):
            return Response({'detail': 'Too many requests. Please try again shortly.'},
                             status=status.HTTP_429_TOO_MANY_REQUESTS)

        serializer = ResendOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        try:
            user = User.objects.get(email__iexact=email, is_active=True, is_deleted=False)
        except User.DoesNotExist:
            return Response({'detail': 'If an account exists for that email, a new code has been sent.'})

        try:
            issue_otp(user, async_send=True)
        except OtpCooldownError as exc:
            return Response(
                {'detail': f'Please wait {exc.retry_after_seconds}s before requesting another code.',
                 'retry_after_seconds': exc.retry_after_seconds},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        return Response({'detail': 'If an account exists for that email, a new code has been sent.'})


@method_decorator(ratelimit(key=ratelimit_ip_key, rate='10/m', method='POST', block=False), name='post')
class VerifyOtpResetView(APIView):
    permission_classes = [AllowAny]
    MAX_ATTEMPTS = 5

    def post(self, request):
        if getattr(request, 'limited', False):
            return Response({'detail': 'Too many requests. Please try again shortly.'},
                             status=status.HTTP_429_TOO_MANY_REQUESTS)

        serializer = VerifyOtpResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        error = {'detail': 'Invalid or expired code.'}
        try:
            user = User.objects.get(email__iexact=data['email'], is_active=True, is_deleted=False)
        except User.DoesNotExist:
            check_hash(data['otp'], _DUMMY_PASSWORD_HASH)
            return Response(error, status=status.HTTP_400_BAD_REQUEST)

        otp = (
            OTPVerification.objects
            .filter(user=user, purpose=OTPVerification.Purpose.PASSWORD_RESET, verified_at__isnull=True)
            .order_by('-created_at')
            .first()
        )
        if not otp or not otp.is_valid():
            check_hash(data['otp'], _DUMMY_PASSWORD_HASH)
            return Response(error, status=status.HTTP_400_BAD_REQUEST)

        if otp.attempt_count >= self.MAX_ATTEMPTS:
            return Response({'detail': 'Too many incorrect attempts. Request a new code.'},
                             status=status.HTTP_400_BAD_REQUEST)

        if not check_hash(data['otp'], otp.otp_code_hash):
            otp.attempt_count += 1
            otp.save(update_fields=['attempt_count'])
            return Response(error, status=status.HTTP_400_BAD_REQUEST)

        # Reuse check happens ONLY here, after the OTP itself has been proven correct -
        # doing it any earlier (e.g. in the serializer, keyed off just the email) would let
        # an attacker probe "is this string someone's current password" for any account
        # without ever needing to know their actual OTP.
        if is_password_reused(user, data['new_password']):
            return Response(
                {'new_password': [f'Cannot reuse your current password or your last '
                                   f'{settings.PASSWORD_HISTORY_COUNT} passwords.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        record_password_history(user)
        user.set_password(data['new_password'])
        user.save(update_fields=['password_hash', 'password_changed_at'])
        otp.verified_at = timezone.now()
        otp.save(update_fields=['verified_at'])
        _log(request, user, 'password_reset')

        return Response({'detail': 'Password has been reset. You can now log in.'})


@method_decorator(ratelimit(key=ratelimit_ip_key, rate='20/m', method='POST', block=False), name='post')
class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if getattr(request, 'limited', False):
            return Response({'detail': 'Too many requests. Please try again shortly.'},
                             status=status.HTTP_429_TOO_MANY_REQUESTS)

        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)  # includes the reuse check (see ChangePasswordSerializer)
        user = request.user
        record_password_history(user)
        user.set_password(serializer.validated_data['new_password'])
        user.save(update_fields=['password_hash', 'password_changed_at'])
        _log(request, user, 'password_change')

        # Reissue tokens so this session (which just proved it knows the old password)
        # continues seamlessly, while any OTHER outstanding session/stolen token - whose
        # iat predates this change - is now rejected (see token_issued_before_password_change).
        raw_refresh = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if raw_refresh:
            revoke_refresh_token(raw_refresh)
        refresh_token, access_token = issue_tokens_for_user(user)

        response = Response({
            'detail': 'Password updated.',
            'access_token': access_token,
            'user': UserProfileSerializer(user).data,
        })
        _set_refresh_cookie(response, refresh_token)
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserProfileSerializer(request.user).data)
