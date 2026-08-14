import io
import logging
import urllib.error
import urllib.request
import zipfile

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from django.db.models import Prefetch, Q
from django.http import Http404, HttpResponse
from django.utils.decorators import method_decorator
from django.utils.dateparse import parse_date
from django_ratelimit.decorators import ratelimit
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import AuditLog, Batch, Candidate, ExamAttempt
from api.pagination import StandardResultsPagination
from api.permissions import IsAdminOrTA
from api.serializers.candidates import (
    CandidateDetailSerializer,
    CandidateListSerializer,
    CandidateUpdateSerializer,
    _ACTIVITY_STATUS_LABELS,
    _effective_status,
    _latest_attempt,
)
from api.services.access import can_access_batch, visible_candidates_qs
from api.services.audit import log_action
from api.services.candidate_history import build_candidate_history
from api.services.email_templates import (
    CERTIFICATION_TEMPLATE, NOTIFICATION_TEMPLATES, render_certification_email, render_template,
)
from api.services.excel_upload import generate_candidates_workbook
from api.services.invites import (
    create_single_reinvite, partition_by_deliverable, send_invites_async, send_notification_emails,
)
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


# Overall score lives on Candidate; per-section scores only exist on the ExamAttempt, so a
# section filter has to reach through the related attempt. Both are exposed as <field>_min /
# <field>_max query params so one shared filter UI can drive them all.
_SCORE_FILTER_FIELDS = {
    'score': 'overall_score',
    'logical': 'examattempt__logical_score',
    'quantitative': 'examattempt__quantitative_score',
    'verbal': 'examattempt__verbal_score',
    'programming': 'examattempt__programming_score',
}


def _apply_score_filters(qs, params):
    """Apply any overall/section score range filters present in the query params."""
    section_filter_applied = False
    for param_prefix, field in _SCORE_FILTER_FIELDS.items():
        for suffix, lookup in (('min', 'gte'), ('max', 'lte')):
            value = _to_decimal_param(params.get(f'{param_prefix}_{suffix}'))
            if value is None:
                continue
            qs = qs.filter(**{f'{field}__{lookup}': value})
            if field.startswith('examattempt__'):
                section_filter_applied = True

    # Joining through examattempt yields one row per attempt, so a candidate with more than
    # one attempt in range would appear twice. Only pay for DISTINCT when a section filter
    # actually introduced the join.
    return qs.distinct() if section_filter_applied else qs


def attach_latest_activity(candidates):
    """Bulk-attach each candidate's most recent outreach audit row in ONE query.

    AuditLog has no FK to Candidate (entity_type/entity_id is a generic pointer), so this can't
    be a prefetch_related - without it the Status column would fire a query per row, which on a
    remote database is a full network round-trip each. Sets `prefetched_latest_activity`, which
    serializers/candidates.py's `_latest_activity` reads in preference to querying.
    """
    candidates = list(candidates)
    if not candidates:
        return candidates

    latest = {}
    rows = AuditLog.objects.filter(
        entity_type='candidate',
        entity_id__in=[c.candidate_id for c in candidates],
        action_type__in=_ACTIVITY_STATUS_LABELS,
    ).order_by('-created_at').only('entity_id', 'action_type', 'action_details', 'created_at')
    for row in rows:
        # Ordered newest-first, so the first row seen per candidate is the one we want.
        latest.setdefault(row.entity_id, row)

    for candidate in candidates:
        candidate.prefetched_latest_activity = latest.get(candidate.candidate_id)
    return candidates


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

        qs = _apply_score_filters(qs, request.query_params)

        qs = _with_latest_attempt(qs.order_by('-created_at'))
        paginator = StandardResultsPagination()
        page = attach_latest_activity(paginator.paginate_queryset(qs, request, view=self))
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


class CandidateHistoryView(APIView):
    """Backs the "View History" action on the bulk-upload review table and the candidate
    tables. Returns an empty `events` list rather than a 404 when there's nothing recorded -
    the UI renders that as the wireframe's "No history found" empty state.
    """
    permission_classes = [IsAdminOrTA]

    def get(self, request, candidate_id):
        candidate = _get_candidate_or_404(request.user, candidate_id)
        return Response({
            'candidate_id': candidate.candidate_id,
            'full_name': candidate.full_name,
            'events': build_candidate_history(candidate),
        })


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


class NotificationTemplateListView(APIView):
    """Serves the approved template copy to the notify modal, so the wording lives only in
    services/email_templates.py rather than being duplicated in the frontend bundle.
    """
    permission_classes = [IsAdminOrTA]

    def get(self, request):
        return Response([
            {'key': key, 'label': template['label'],
             'subject': template['subject'], 'body': template['body']}
            for key, template in NOTIFICATION_TEMPLATES.items()
        ])


@method_decorator(ratelimit(key=ratelimit_user_key, rate='10/m', method='POST', block=False), name='post')
class CandidateNotifyView(APIView):
    permission_classes = [IsAdminOrTA]

    def post(self, request):
        if getattr(request, 'limited', False):
            return Response({'detail': 'Too many notification requests. Please try again shortly.'},
                             status=status.HTTP_429_TOO_MANY_REQUESTS)

        candidate_ids = request.data.get('candidate_ids', [])
        template_key = (request.data.get('template') or '').strip()
        message = (request.data.get('message') or '').strip()

        if not isinstance(candidate_ids, list) or not candidate_ids:
            return Response({'detail': 'Select at least one candidate to notify.'},
                             status=status.HTTP_400_BAD_REQUEST)

        template = NOTIFICATION_TEMPLATES.get(template_key) if template_key else None
        if template_key and not template:
            return Response({'detail': f'Unknown email template "{template_key}".'},
                             status=status.HTTP_400_BAD_REQUEST)
        if not template and not message:
            return Response({'detail': 'Pick a template or write a message first.'},
                             status=status.HTTP_400_BAD_REQUEST)

        candidates = list(visible_candidates_qs(request.user).filter(candidate_id__in=candidate_ids))
        if not candidates:
            return Response({'detail': 'No matching candidates found.'},
                             status=status.HTTP_400_BAD_REQUEST)

        # An unedited template sends the approved copy verbatim (personalised per recipient);
        # anything the TA typed over it wins, since they edited it deliberately.
        if template:
            subject = request.data.get('subject') or template['subject']
            body_for = (lambda c: message) if message else (lambda c: render_template(template_key, c)[1])
        else:
            subject = request.data.get('subject') or 'Accelirate TalentGate - Update'
            body_for = lambda c: message  # noqa: E731 - trivial constant-body case

        sendable, skipped = partition_by_deliverable(candidates)
        if not sendable:
            return Response(
                {'detail': f'None of the {len(skipped)} selected candidate(s) have an email '
                            f'address on record, so nothing was sent.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        send_notification_emails(sendable, subject.strip(), body_for)
        for candidate in sendable:
            log_action(request, request.user, 'notify_sent', 'candidate', candidate.candidate_id,
                       details={'subject': subject, 'template': template_key or 'custom'})

        detail = f'{len(sendable)} notification(s) queued for sending.'
        if skipped:
            detail += (f' {len(skipped)} skipped - no email address on record '
                       f'({", ".join(c.full_name or f"#{c.candidate_id}" for c in skipped[:3])}'
                       f'{"..." if len(skipped) > 3 else ""}).')
        return Response({'notified_count': len(sendable), 'skipped_count': len(skipped),
                         'detail': detail})


@method_decorator(ratelimit(key=ratelimit_user_key, rate='10/m', method='POST', block=False), name='post')
class CandidateCertificationView(APIView):
    """Send the fixed certification email to a checked shortlist, with two TA-supplied links.

    The copy lives in email_templates.CERTIFICATION_TEMPLATE and is not editable from the UI -
    the TA supplies only the two URLs, so approved wording can't drift per-send.
    """
    permission_classes = [IsAdminOrTA]

    def post(self, request):
        if getattr(request, 'limited', False):
            return Response({'detail': 'Too many certification requests. Please try again shortly.'},
                             status=status.HTTP_429_TOO_MANY_REQUESTS)

        candidate_ids = request.data.get('candidate_ids', [])
        link_one = (request.data.get('link_one') or '').strip()
        link_two = (request.data.get('link_two') or '').strip()

        if not isinstance(candidate_ids, list) or not candidate_ids:
            return Response({'detail': 'Select at least one candidate first.'},
                             status=status.HTTP_400_BAD_REQUEST)
        if not link_one or not link_two:
            return Response({'detail': 'Both certification links are required.'},
                             status=status.HTTP_400_BAD_REQUEST)

        validate_url = URLValidator(schemes=['http', 'https'])
        for label, link in (('Link 1', link_one), ('Link 2', link_two)):
            try:
                validate_url(link)
            except DjangoValidationError:
                return Response(
                    {'detail': f'{label} is not a valid URL - it should start with https://'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        candidates = list(visible_candidates_qs(request.user).filter(candidate_id__in=candidate_ids))
        if not candidates:
            return Response({'detail': 'No matching candidates found.'},
                             status=status.HTTP_400_BAD_REQUEST)

        sendable, skipped = partition_by_deliverable(candidates)
        if not sendable:
            return Response(
                {'detail': f'None of the {len(skipped)} selected candidate(s) have an email '
                            f'address on record, so nothing was sent.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        subject = CERTIFICATION_TEMPLATE['subject']
        send_notification_emails(
            sendable, subject,
            lambda c: render_certification_email(c, link_one, link_two)[1],
        )
        for candidate in sendable:
            log_action(request, request.user, 'certification_sent', 'candidate', candidate.candidate_id,
                       details={'subject': subject})

        detail = f'Certification links queued for {len(sendable)} candidate(s).'
        if skipped:
            detail += f' {len(skipped)} skipped - no email address on record.'
        return Response({'notified_count': len(sendable), 'skipped_count': len(skipped),
                         'detail': detail})


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

        # attach_latest_activity so exported Status cells match what the table shows.
        wb = generate_candidates_workbook(
            attach_latest_activity(_with_latest_attempt(qs)), _latest_attempt,
            status_display_fn=lambda c: _effective_status(c)[1],
        )
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
