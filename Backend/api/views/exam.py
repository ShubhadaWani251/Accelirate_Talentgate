"""Candidate-facing exam-taking portal - everything behind the /t/<token> link.

Deliberately separate authentication/permission story from the rest of the API: candidates
aren't api.User rows at all, so the fully-public endpoints below (token landing, email
verification, identity capture) explicitly clear authentication_classes rather than relying on
the global CustomJWTAuthentication default, and every endpoint from identity capture onward
authenticates via CandidateAttemptAuthentication (api/authentication.py) instead.
"""

import logging

from django.utils import timezone
from django.utils.decorators import method_decorator
from django.http import Http404
from django_ratelimit.decorators import ratelimit
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.authentication import CandidateAttemptAuthentication
from api.models import ExamAnswer, ExamAttempt, Invitation, ProctoringEvent
from api.serializers.exam import AnswerSerializer, EmailVerifySerializer, TerminateSerializer
from api.services import blob_storage, exam_session
from api.services.exam_session import TERMINATION_MESSAGES, TerminationReason, is_violation_reason
from api.services.question_selection import SECTION_LABELS, SECTION_ORDER, InsufficientQuestionsError
from api.services.tokens import issue_attempt_token
from api.utils.net import get_client_ip, ratelimit_ip_key

logger = logging.getLogger(__name__)


def _get_invitation(token):
    try:
        return Invitation.objects.select_related('batch', 'candidate').get(unique_link_token=token)
    except Invitation.DoesNotExist:
        return None


def _instructions_payload(invitation):
    batch = invitation.batch
    sections = []
    for key in SECTION_ORDER:
        count = getattr(batch, f'{key}_questions')
        if count <= 0:
            continue
        sections.append({
            'key': key,
            'label': SECTION_LABELS[key],
            'question_count': count,
            'cutoff': float(getattr(batch, f'{key}_cutoff')),
        })
    return {
        'batch_name': batch.batch_name,
        'candidate_name': invitation.candidate.full_name,
        'exam_duration_minutes': batch.exam_duration_minutes,
        'total_questions': sum(s['question_count'] for s in sections),
        'sections': sections,
    }


def _result_payload(attempt):
    batch = attempt.invitation.batch
    sections = []
    for key in SECTION_ORDER:
        total = getattr(batch, f'{key}_questions')
        if total <= 0:
            continue
        sections.append({
            'key': key,
            'label': SECTION_LABELS[key],
            'score': getattr(attempt, f'{key}_score'),
            'total': total,
            'cutoff': float(getattr(batch, f'{key}_cutoff')),
            'cleared': getattr(attempt, f'{key}_cleared'),
        })
    return {
        'result': attempt.candidate.result,
        'total_correct': attempt.total_correct,
        'total_answered': attempt.total_answered,
        'total_questions': sum(s['total'] for s in sections),
        'sections': sections,
    }


@method_decorator(ratelimit(key=ratelimit_ip_key, rate='10/m', method='GET', block=False), name='get')
class ExamTokenLandingView(APIView):
    """GET /api/exam/token/<token>/ - screen c-verify's initial load. Never reveals the
    candidate's identity off a bare token; that only happens once the email is confirmed
    (ExamVerifyEmailView).
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token):
        if getattr(request, 'limited', False):
            return Response({'reason': 'invalid'}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        invitation = _get_invitation(token)
        if invitation is None:
            return Response({'reason': 'invalid'})

        if not invitation.link_clicked_at:
            invitation.link_clicked_at = timezone.now()
            invitation.save(update_fields=['link_clicked_at'])

        if invitation.link_expired_at < timezone.now():
            return Response({'reason': 'expired'})

        attempt = ExamAttempt.objects.filter(invitation=invitation).first()
        if attempt is None:
            return Response({'reason': 'ok', 'resume': False})

        if attempt.status == ExamAttempt.Status.IN_PROGRESS and exam_session.is_expired(attempt):
            exam_session.finalize_attempt(attempt, outcome='submitted')
            attempt.refresh_from_db()

        if attempt.status != ExamAttempt.Status.IN_PROGRESS:
            return Response({'reason': 'completed'})
        return Response({'reason': 'ok', 'resume': True})


@method_decorator(ratelimit(key=ratelimit_ip_key, rate='10/m', method='POST', block=False), name='post')
class ExamVerifyEmailView(APIView):
    """POST /api/exam/token/<token>/verify-email/ - screen c-verify's "Continue". Matching
    email proceeds to Instructions (fresh start) or straight back into an in-progress attempt
    (resume, see plan §8) with a freshly-minted attempt JWT.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, token):
        if getattr(request, 'limited', False):
            return Response({'detail': 'Too many attempts. Please try again shortly.'},
                             status=status.HTTP_429_TOO_MANY_REQUESTS)

        serializer = EmailVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].strip().lower()

        invitation = _get_invitation(token)
        if invitation is None or invitation.link_expired_at < timezone.now():
            return Response({'detail': 'This assessment link is invalid or has expired.'},
                             status=status.HTTP_400_BAD_REQUEST)

        if invitation.candidate.email.strip().lower() != email:
            return Response(
                {'detail': 'That email does not match the address this assessment link was sent to.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        attempt = (
            ExamAttempt.objects.select_related('invitation', 'invitation__batch', 'candidate')
            .filter(invitation=invitation)
            .first()
        )
        if attempt and attempt.status == ExamAttempt.Status.IN_PROGRESS:
            if exam_session.is_expired(attempt):
                exam_session.finalize_attempt(attempt, outcome='submitted')
                return Response({'detail': 'This assessment has already ended.'},
                                 status=status.HTTP_400_BAD_REQUEST)
            return Response({
                'resume': True,
                'attempt_token': issue_attempt_token(attempt),
                **exam_session.build_session_state(attempt),
            })
        if attempt:  # SUBMITTED or TERMINATED
            return Response({'detail': 'This assessment has already been completed.'},
                             status=status.HTTP_400_BAD_REQUEST)

        return Response({'resume': False, **_instructions_payload(invitation)})


@method_decorator(ratelimit(key=ratelimit_ip_key, rate='5/m', method='POST', block=False), name='post')
class ExamIdentityCaptureView(APIView):
    """POST /api/exam/token/<token>/identity/ - screen c-idverify. Creates the ExamAttempt (or
    fetches the one already created by a retried submit) and its randomized question set, then
    uploads both captured photos. v1 stub: no automated face-match, see plan's escalated
    decision - photos are stored for the TA's manual review only.
    """
    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser]

    def post(self, request, token):
        if getattr(request, 'limited', False):
            return Response({'detail': 'Too many attempts. Please try again shortly.'},
                             status=status.HTTP_429_TOO_MANY_REQUESTS)

        invitation = _get_invitation(token)
        if invitation is None or invitation.link_expired_at < timezone.now():
            return Response({'detail': 'This assessment link is invalid or has expired.'},
                             status=status.HTTP_400_BAD_REQUEST)

        id_photo = request.FILES.get('id_photo')
        face_photo = request.FILES.get('face_photo')
        if not id_photo or not face_photo:
            return Response({'detail': 'Both an ID photo and a face photo are required.'},
                             status=status.HTTP_400_BAD_REQUEST)

        try:
            attempt, _created = exam_session.start_or_resume_attempt(
                invitation.pk, get_client_ip(request), request.META.get('HTTP_USER_AGENT', ''),
            )
        except InsufficientQuestionsError as exc:
            logger.error('Cannot start attempt for invitation_id=%s: %s', invitation.pk, exc)
            return Response(
                {'detail': 'This assessment cannot be started right now. Please contact support.'},
                status=status.HTTP_409_CONFLICT,
            )

        if attempt.status != ExamAttempt.Status.IN_PROGRESS:
            return Response({'detail': 'This assessment has already been completed.'},
                             status=status.HTTP_400_BAD_REQUEST)

        if not attempt.id_verified_at:
            try:
                attempt.aadhaar_capture_url = blob_storage.upload_photo(
                    attempt.attempt_id, 'id_photo', id_photo.read(), id_photo.content_type,
                )
                attempt.face_photo_url = blob_storage.upload_photo(
                    attempt.attempt_id, 'face_photo', face_photo.read(), face_photo.content_type,
                )
                attempt.id_verified_at = timezone.now()
                attempt.session_recording_url = blob_storage.start_recording_blob(attempt.attempt_id)
            except Exception:
                # A storage failure here (misconfigured/unreachable Azure) must not surface as an
                # unhandled 500 with no JSON body - the frontend can only show a specific message
                # if there's a `detail` to read.
                logger.exception(
                    'Evidence upload failed for attempt_id=%s (invitation_id=%s)',
                    attempt.attempt_id, invitation.pk,
                )
                return Response(
                    {'detail': 'Photo upload failed - evidence storage is unavailable right now. '
                               'Please try again in a moment.'},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            attempt.save(update_fields=[
                'aadhaar_capture_url', 'face_photo_url', 'id_verified_at', 'session_recording_url',
            ])

        return Response({
            'attempt_token': issue_attempt_token(attempt),
            **exam_session.build_session_state(attempt),
        })


class ExamBeginView(APIView):
    """POST /api/exam/begin/ - starts the clock, called once the candidate is actually looking at
    the exam window (not at identity capture). Idempotent: a reload/resume keeps the original
    started_at rather than handing out a fresh full duration.
    """
    authentication_classes = [CandidateAttemptAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        attempt = exam_session.begin_exam(request.user)
        return Response(exam_session.build_session_state(attempt))


class ExamSessionView(APIView):
    """GET /api/exam/session/ - full render/resume state for screen c-exam.

    Deliberately does NOT start the clock - only ExamBeginView does, so merely reading state can
    never begin the exam.
    """
    authentication_classes = [CandidateAttemptAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(exam_session.build_session_state(request.user))


class ExamAnswerView(APIView):
    """PATCH /api/exam/answers/<question_id>/ - autosave, one question at a time."""
    authentication_classes = [CandidateAttemptAuthentication]
    permission_classes = [IsAuthenticated]

    def patch(self, request, question_id):
        serializer = AnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            answer = exam_session.save_answer(
                request.user, question_id,
                serializer.validated_data.get('selected_option'),
                serializer.validated_data.get('time_spent_seconds'),
            )
        except ExamAnswer.DoesNotExist:
            raise Http404
        return Response({'question_id': question_id, 'selected_option': answer.selected_option})


@method_decorator(ratelimit(key=ratelimit_ip_key, rate='30/m', method='POST', block=False), name='post')
class ExamRecordingChunkView(APIView):
    """POST /api/exam/recording/chunk/ - raw binary body, one ~10s MediaRecorder chunk,
    appended to the attempt's Azure append-blob. Body is read via request.body (Django's raw
    bytes) rather than any DRF parser, since the content isn't JSON/form/multipart.
    """
    authentication_classes = [CandidateAttemptAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if getattr(request, 'limited', False):
            return Response({'detail': 'Too many chunks.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        if not request.body:
            return Response({'detail': 'Empty chunk.'}, status=status.HTTP_400_BAD_REQUEST)
        blob_storage.append_recording_chunk(request.user.attempt_id, request.body)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExamTerminateView(APIView):
    """POST /api/exam/terminate/ - the candidate's browser calls this the instant any
    zero-tolerance trigger fires (tab switch, window blur, full-screen exit, a devtools/
    view-source/screenshot key, or camera/mic loss - see the frontend's proctoring hooks).
    First call wins (idempotent no-op if the attempt is already finalized by the time this
    lands). `reason` drives both the stored ProctoringEvent/termination_reason and the specific
    message returned to the candidate - never a single generic message regardless of cause.
    """
    authentication_classes = [CandidateAttemptAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TerminateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason_code = serializer.validated_data.get('reason', TerminationReason.TAB_SWITCH)

        attempt = request.user
        if attempt.status == ExamAttempt.Status.IN_PROGRESS:
            ProctoringEvent.objects.create(
                attempt=attempt, event_type=reason_code,
                is_violation=is_violation_reason(reason_code),
                severity=ProctoringEvent.Severity.CRITICAL,
            )
            exam_session.finalize_attempt(attempt, outcome='terminated', reason=reason_code)
        return Response({'detail': TERMINATION_MESSAGES[reason_code], 'reason': reason_code})


class ExamSubmitView(APIView):
    """POST /api/exam/submit/ - screen c-submit's confirmed submit, and also what a
    time-expiry auto-finalize (see CandidateAttemptAuthentication) effectively performs."""
    authentication_classes = [CandidateAttemptAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        attempt = exam_session.finalize_attempt(request.user, outcome='submitted')
        return Response(_result_payload(attempt))
