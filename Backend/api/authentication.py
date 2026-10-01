from datetime import timedelta

from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.settings import api_settings

from api.models import ExamAttempt, User
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


# How stale last_activity_at may get before the next authenticated request rewrites it. Must stay
# comfortably below terminate_stale_attempts' DEFAULT_THRESHOLD_SECONDS (60) - that command reads
# this column to decide an attempt has gone silent, so writing less often than it checks would end
# live candidates' exams. 20s is a third of it.
HEARTBEAT_RESOLUTION = timedelta(seconds=20)


class CandidateAttemptAuthentication(JWTAuthentication):
    """Resolves a JWT's `attempt_id` claim to an ExamAttempt, not a User - the exam-taking
    portal's candidates aren't in api.User at all (see services/tokens.issue_attempt_token for
    how this token is minted). request.user ends up being the ExamAttempt itself; that's safe
    because every candidate-facing view only ever reads it as "the current attempt," never as
    something with a `.role` for IsAdminOrTA-style checks.

    Also enforces the exam's timer here rather than in each view individually: an attempt whose
    deadline (started_at + batch.exam_duration_minutes) has passed is auto-finalized on the way
    out, so a tampered client-side countdown can never buy extra writes past the real deadline.
    """

    def get_user(self, validated_token):
        # Deferred import: services.exam_session pulls in services.question_selection, which
        # only api.models needs - avoids any chance of a load-order cycle with authentication.py
        # being imported very early (it's on DEFAULT_AUTHENTICATION_CLASSES).
        from api.services import exam_session

        try:
            attempt_id = validated_token['attempt_id']
        except KeyError:
            raise InvalidToken('Token contained no attempt identification')

        try:
            attempt = ExamAttempt.objects.select_related(
                'candidate', 'invitation', 'invitation__batch'
            ).get(attempt_id=attempt_id)
        except ExamAttempt.DoesNotExist:
            raise AuthenticationFailed('Attempt not found', code='attempt_not_found')

        if attempt.status != ExamAttempt.Status.IN_PROGRESS:
            raise AuthenticationFailed('This attempt is no longer active', code='attempt_closed')

        if exam_session.is_expired(attempt):
            exam_session.finalize_attempt(attempt, outcome='submitted')
            raise AuthenticationFailed('Time expired for this attempt', code='attempt_expired')

        # A heartbeat, not just bookkeeping: this is what
        # management/commands/terminate_stale_attempts.py watches to notice a closed browser/SEB
        # process mid-exam (see ExamAttempt.last_activity_at's own comment for why nothing more
        # direct is possible). Every authenticated candidate request refreshes it - not just the
        # recording-chunk upload - so an attempt still counts as "alive" for as long as anything
        # at all is coming from it.
        #
        # Throttled, because this used to write on EVERY authenticated request. Answer autosaves
        # and violation reports arrive on top of the chunk uploads, so a busy candidate was
        # issuing a DB UPDATE several times a minute purely to restate that they were still
        # there - multiplied by every concurrent candidate, against a database whose connection
        # budget is the tightest resource this deployment has.
        #
        # HEARTBEAT_RESOLUTION has to stay well under terminate_stale_attempts' own threshold
        # (60s): the sweep treats an attempt as gone when last_activity_at is older than that,
        # so writing less often than it reads would terminate live candidates. A third of the
        # threshold leaves room for a slow request without ever approaching it.
        now = timezone.now()
        if (attempt.last_activity_at is None
                or (now - attempt.last_activity_at) >= HEARTBEAT_RESOLUTION):
            attempt.last_activity_at = now
            attempt.save(update_fields=['last_activity_at'])

        return attempt
