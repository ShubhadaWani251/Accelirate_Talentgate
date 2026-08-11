import logging

from django.conf import settings
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Batch, Candidate, Question, QuestionBankSection, User
from api.permissions import IsAdminOrTA
from api.serializers.candidates import (
    CandidateDetailSerializer,
    CandidateListSerializer,
    CandidateUpdateSerializer,
    _latest_attempt,
)
from api.services.audit import log_action
from api.services.excel_upload import generate_candidates_workbook
from api.services.invites import create_single_reinvite, send_invites_async, send_notification_emails
from api.views.batches import _can_access_batch

logger = logging.getLogger(__name__)


def _visible_candidates_qs(user):
    qs = Candidate.objects.select_related('batch').filter(is_deleted=False, batch__is_deleted=False)
    if user.role.role_code != 'admin':
        qs = qs.filter(Q(batch__primary_ta_user_id=user.user_id) | Q(batch__created_by_id=user.user_id))
    return qs


def _get_candidate_or_404(user, candidate_id):
    try:
        candidate = Candidate.objects.select_related('batch').get(
            candidate_id=candidate_id, is_deleted=False, batch__is_deleted=False,
        )
    except Candidate.DoesNotExist:
        raise Http404
    if not _can_access_batch(user, candidate.batch):
        raise Http404  # don't reveal existence of candidates the caller can't access
    return candidate


def _to_decimal_param(value):
    try:
        return float(value) if value not in (None, '') else None
    except ValueError:
        return None


class CandidateListView(APIView):
    permission_classes = [IsAdminOrTA]

    def get(self, request):
        qs = _visible_candidates_qs(request.user)

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

        qs = qs.order_by('-created_at')
        return Response(CandidateListSerializer(qs, many=True).data)


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


class CandidateNotifyView(APIView):
    permission_classes = [IsAdminOrTA]

    def post(self, request):
        candidate_ids = request.data.get('candidate_ids', [])
        subject = (request.data.get('subject') or 'Accelirate TalentGate - Update').strip()
        message = (request.data.get('message') or '').strip()

        if not isinstance(candidate_ids, list) or not candidate_ids:
            return Response({'detail': 'candidate_ids must be a non-empty list.'},
                             status=status.HTTP_400_BAD_REQUEST)
        if not message:
            return Response({'detail': 'A message is required.'}, status=status.HTTP_400_BAD_REQUEST)

        candidates = list(_visible_candidates_qs(request.user).filter(candidate_id__in=candidate_ids))
        if not candidates:
            return Response({'detail': 'No matching candidates found.'},
                             status=status.HTTP_400_BAD_REQUEST)

        send_notification_emails(candidates, subject, message)
        for candidate in candidates:
            log_action(request, request.user, 'notify_sent', 'candidate', candidate.candidate_id,
                       details={'subject': subject})

        return Response({'notified_count': len(candidates)})


class CandidateExportView(APIView):
    permission_classes = [IsAdminOrTA]

    def get(self, request):
        qs = _visible_candidates_qs(request.user).order_by('-created_at')

        batch_id = request.query_params.get('batch_id')
        if batch_id:
            qs = qs.filter(batch_id=batch_id)

        date_from = parse_date(request.query_params.get('from', '') or '')
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)

        date_to = parse_date(request.query_params.get('to', '') or '')
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        wb = generate_candidates_workbook(qs, _latest_attempt)
        buffer_response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        buffer_response['Content-Disposition'] = 'attachment; filename="candidates_export.xlsx"'
        wb.save(buffer_response)
        return buffer_response


class DashboardSummaryView(APIView):
    permission_classes = [IsAdminOrTA]

    def get(self, request):
        user = request.user
        is_admin = user.role.role_code == 'admin'

        batches_qs = Batch.objects.filter(is_deleted=False)
        if not is_admin:
            batches_qs = batches_qs.filter(
                Q(primary_ta_user_id=user.user_id) | Q(created_by_id=user.user_id)
            )
        candidates_qs = _visible_candidates_qs(user)

        stats = {
            'active_batches': batches_qs.filter(status=Batch.Status.IN_PROGRESS).count(),
            'total_candidates': candidates_qs.count(),
            'completed': candidates_qs.filter(status=Candidate.Status.COMPLETED).count(),
            'total_pass': candidates_qs.filter(result=Candidate.Result.PASS).count(),
        }

        batches_overview = []
        for batch in batches_qs.select_related('primary_ta_user').order_by('-created_at'):
            row = {
                'batch_id': batch.batch_id,
                'batch_name': batch.batch_name,
                'college_name': batch.college_name,
                'total_candidates': batch.total_candidates,
                'status': batch.status,
                'status_display': batch.get_status_display(),
                'pass_count': batch.candidate_set.filter(result=Candidate.Result.PASS,
                                                         is_deleted=False).count(),
                'fail_count': batch.candidate_set.filter(result=Candidate.Result.FAIL,
                                                         is_deleted=False).count(),
                'borderline_count': 0,
            }
            if is_admin:
                row['primary_ta_user_name'] = batch.primary_ta_user.full_name
            batches_overview.append(row)

        response = {'stats': stats, 'batches_overview': batches_overview}

        if is_admin:
            response['question_bank_health'] = [
                {
                    'section_name': section.section_name,
                    'active_count': (active_count := section.question_set.filter(
                        status=Question.Status.ACTIVE).count()),
                    'min_required_active': section.min_required_active,
                    'is_ok': active_count >= section.min_required_active,
                }
                for section in QuestionBankSection.objects.all()
            ]
            response['ta_accounts'] = [
                {
                    'user_id': u.user_id,
                    'full_name': u.full_name,
                    'role_name': u.role.role_name,
                    'is_active': u.is_active,
                }
                for u in User.objects.filter(is_deleted=False).select_related('role').order_by('first_name')
            ]

        return Response(response)
