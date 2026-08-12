import io
import logging
import urllib.error
import urllib.request
import zipfile

from django.conf import settings
from django.db.models import Prefetch, Q
from django.http import Http404, HttpResponse
from django.utils.decorators import method_decorator
from django.utils.dateparse import parse_date
from django_ratelimit.decorators import ratelimit
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Batch, Candidate, ExamAttempt
from api.pagination import StandardResultsPagination
from api.permissions import IsAdminOrTA
from api.serializers.candidates import (
    CandidateDetailSerializer,
    CandidateListSerializer,
    CandidateUpdateSerializer,
    _latest_attempt,
)
from api.services.access import can_access_batch, visible_candidates_qs
from api.services.audit import log_action
from api.services.excel_upload import generate_candidates_workbook
from api.services.invites import create_single_reinvite, send_invites_async, send_notification_emails
from api.utils.net import ratelimit_user_key

logger = logging.getLogger(__name__)


def _get_candidate_or_404(user, candidate_id):
    try:
        candidate = Candidate.objects.select_related('batch').get(
            candidate_id=candidate_id, is_deleted=False, batch__is_deleted=False,
        )
    except Candidate.DoesNotExist:
        raise Http404
    if not can_access_batch(user, candidate.batch):
        raise Http404  # don't reveal existence of candidates the caller can't access
    return candidate


def _to_decimal_param(value):
    try:
        return float(value) if value not in (None, '') else None
    except ValueError:
        return None


def _with_latest_attempt(qs):
    """Prefetch each candidate's most recent ExamAttempt in one extra query instead of one
    query per candidate - serializers/candidates.py's _latest_attempt reads the resulting
    `prefetched_latest_attempts` list instead of querying per-instance.
    """
    return qs.prefetch_related(
        Prefetch('examattempt_set', queryset=ExamAttempt.objects.order_by('-started_at'),
                 to_attr='prefetched_latest_attempts')
    )


class CandidateListView(APIView):
    permission_classes = [IsAdminOrTA]

    def get(self, request):
        qs = visible_candidates_qs(request.user)

        name = request.query_params.get('name', '').strip()
        if name:
            qs = qs.filter(Q(first_name__icontains=name) | Q(last_name__icontains=name))

        email = request.query_params.get('email', '').strip()
        if email:
            qs = qs.filter(email__icontains=email)

        aadhaar = request.query_params.get('aadhaar', '').strip()
        if aadhaar:
            qs = qs.filter(aadhaar_number__icontains=aadhaar)

        batch_id = request.query_params.get('batch_id')
        if batch_id:
            qs = qs.filter(batch_id=batch_id)

        result = request.query_params.get('result', '').strip()
        if result:
            qs = qs.filter(result=result)

        score_min = _to_decimal_param(request.query_params.get('score_min'))
        if score_min is not None:
            qs = qs.filter(overall_score__gte=score_min)

        score_max = _to_decimal_param(request.query_params.get('score_max'))
        if score_max is not None:
            qs = qs.filter(overall_score__lte=score_max)

        qs = _with_latest_attempt(qs.order_by('-created_at'))
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(CandidateListSerializer(page, many=True).data)


class CandidateDetailView(APIView):
    permission_classes = [IsAdminOrTA]

    def get(self, request, candidate_id):
        candidate = _get_candidate_or_404(request.user, candidate_id)
        return Response(CandidateDetailSerializer(candidate).data)

    def patch(self, request, candidate_id):
        candidate = _get_candidate_or_404(request.user, candidate_id)
        serializer = CandidateUpdateSerializer(candidate, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        log_action(request, request.user, 'update', 'candidate', candidate.candidate_id)
        return Response(CandidateDetailSerializer(candidate).data)


class CandidateResendInviteView(APIView):
    permission_classes = [IsAdminOrTA]

    def post(self, request, candidate_id):
        candidate = _get_candidate_or_404(request.user, candidate_id)
        if candidate.batch.status == Batch.Status.DRAFT:
            return Response({'detail': 'Finalize this batch before sending invites.'},
                             status=status.HTTP_400_BAD_REQUEST)

        invitation = create_single_reinvite(candidate, request.user)
        send_invites_async([invitation], settings.FRONTEND_ORIGIN)
        log_action(request, request.user, 'invite_sent', 'candidate', candidate.candidate_id,
                   details={'re_invite': True})
        return Response({'detail': f'Invite re-sent to {candidate.email}.'})


@method_decorator(ratelimit(key=ratelimit_user_key, rate='10/m', method='POST', block=False), name='post')
class CandidateNotifyView(APIView):
    permission_classes = [IsAdminOrTA]

    def post(self, request):
        if getattr(request, 'limited', False):
            return Response({'detail': 'Too many notification requests. Please try again shortly.'},
                             status=status.HTTP_429_TOO_MANY_REQUESTS)

        candidate_ids = request.data.get('candidate_ids', [])
        subject = (request.data.get('subject') or 'Accelirate TalentGate - Update').strip()
        message = (request.data.get('message') or '').strip()

        if not isinstance(candidate_ids, list) or not candidate_ids:
            return Response({'detail': 'candidate_ids must be a non-empty list.'},
                             status=status.HTTP_400_BAD_REQUEST)
        if not message:
            return Response({'detail': 'A message is required.'}, status=status.HTTP_400_BAD_REQUEST)

        candidates = list(visible_candidates_qs(request.user).filter(candidate_id__in=candidate_ids))
        if not candidates:
            return Response({'detail': 'No matching candidates found.'},
                             status=status.HTTP_400_BAD_REQUEST)

        send_notification_emails(candidates, subject, message)
        for candidate in candidates:
            log_action(request, request.user, 'notify_sent', 'candidate', candidate.candidate_id,
                       details={'subject': subject})

        return Response({'notified_count': len(candidates)})


@method_decorator(ratelimit(key=ratelimit_user_key, rate='10/m', method='GET', block=False), name='get')
class CandidateExportView(APIView):
    permission_classes = [IsAdminOrTA]

    def get(self, request):
        if getattr(request, 'limited', False):
            return Response({'detail': 'Too many export requests. Please try again shortly.'},
                             status=status.HTTP_429_TOO_MANY_REQUESTS)

        qs = visible_candidates_qs(request.user).order_by('-created_at')

        batch_id = request.query_params.get('batch_id')
        if batch_id:
            qs = qs.filter(batch_id=batch_id)

        date_from = parse_date(request.query_params.get('from', '') or '')
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)

        date_to = parse_date(request.query_params.get('to', '') or '')
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        wb = generate_candidates_workbook(_with_latest_attempt(qs), _latest_attempt)
        buffer_response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        buffer_response['Content-Disposition'] = 'attachment; filename="candidates_export.xlsx"'
        wb.save(buffer_response)
        return buffer_response


class CandidateEvidenceZipView(APIView):
    """Bundles a candidate's proctoring evidence (Aadhaar capture, verification photo, session
    recording) into one downloadable zip, fetched server-side from the URLs recorded on their
    latest ExamAttempt so the browser only needs one authenticated request instead of three
    separate (currently unauthenticated) file URLs.
    """
    permission_classes = [IsAdminOrTA]

    EVIDENCE_FILES = [
        ('aadhaar_capture_url', 'aadhaar.jpg'),
        ('face_photo_url', 'face_photo.jpg'),
        ('session_recording_url', 'session_recording.mp4'),
    ]

    def get(self, request, candidate_id):
        candidate = _get_candidate_or_404(request.user, candidate_id)
        attempt = _latest_attempt(candidate)
        if not attempt:
            return Response({'detail': 'No proctoring evidence exists for this candidate yet.'},
                             status=status.HTTP_400_BAD_REQUEST)

        buffer = io.BytesIO()
        fetched_any = False
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for field, filename in self.EVIDENCE_FILES:
                url = getattr(attempt, field)
                if not url:
                    continue
                try:
                    with urllib.request.urlopen(url, timeout=10) as file_response:
                        archive.writestr(filename, file_response.read())
                    fetched_any = True
                except (urllib.error.URLError, ValueError):
                    logger.exception(
                        'Failed to fetch evidence file %s for candidate_id=%s', filename, candidate_id
                    )

        if not fetched_any:
            return Response({'detail': 'No proctoring evidence could be retrieved for this candidate.'},
                             status=status.HTTP_400_BAD_REQUEST)

        buffer.seek(0)
        response = HttpResponse(buffer.read(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="candidate_{candidate_id}_evidence.zip"'
        return response
