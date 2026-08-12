import io
import logging
import zipfile

from django.conf import settings
from django.db import DataError
from django.db.models import Q
from django.http import Http404, HttpResponse
from openpyxl.utils.exceptions import InvalidFileException
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Batch, Candidate, DuplicateCheck, Invitation
from api.pagination import StandardResultsPagination
from api.permissions import IsAdminOrTA
from api.serializers.batch import (
    BatchDefaultsSerializer, BatchSerializer, CandidateStagingSerializer, annotate_batch_counts,
)
from api.services.access import can_access_batch
from api.services.audit import log_action
from api.services.batch_defaults import get_batch_defaults, save_batch_defaults
from api.services.duplicate_check import clear_duplicate
from api.services.excel_upload import generate_template_workbook, stage_candidates_from_workbook
from api.services.invites import create_invitations, send_invites_async

logger = logging.getLogger(__name__)


def _get_batch_or_404(user, batch_id):
    try:
        batch = Batch.objects.select_related('primary_ta_user').get(batch_id=batch_id, is_deleted=False)
    except Batch.DoesNotExist:
        raise Http404
    if not can_access_batch(user, batch):
        raise Http404  # don't reveal existence of batches the caller can't access
    return batch


class BatchListCreateView(APIView):
    permission_classes = [IsAdminOrTA]

    def get(self, request):
        qs = Batch.objects.select_related('primary_ta_user').filter(is_deleted=False)
        if request.user.role.role_code != 'admin':
            qs = qs.filter(primary_ta_user=request.user)
        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(Q(batch_name__icontains=search) | Q(college_name__icontains=search))
        qs = annotate_batch_counts(qs.order_by('-created_at'))
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(BatchSerializer(page, many=True).data)

    def post(self, request):
        serializer = BatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        batch = serializer.save(
            primary_ta_user=request.user,
            created_by=request.user,
            status=Batch.Status.DRAFT,
        )
        log_action(request, request.user, 'create', 'batch', batch.batch_id)
        return Response(BatchSerializer(batch).data, status=status.HTTP_201_CREATED)


class BatchDetailView(APIView):
    permission_classes = [IsAdminOrTA]

    def get(self, request, batch_id):
        batch = _get_batch_or_404(request.user, batch_id)
        return Response(BatchSerializer(batch).data)

    def patch(self, request, batch_id):
        batch = _get_batch_or_404(request.user, batch_id)
        if batch.status != Batch.Status.DRAFT:
            return Response(
                {'detail': 'This batch has already been finalized; its configuration can no '
                            'longer be changed.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = BatchSerializer(batch, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        log_action(request, request.user, 'update', 'batch', batch.batch_id)
        return Response(serializer.data)

    def delete(self, request, batch_id):
        batch = _get_batch_or_404(request.user, batch_id)
        if batch.status == Batch.Status.CANCELLED:
            return Response({'detail': 'This batch is already cancelled.'},
                             status=status.HTTP_400_BAD_REQUEST)

        # Invites already sent means real candidates may already be mid-exam or have results
        # tied to this batch - hard-deleting it would erase that history, so it's deactivated
        # (marked Cancelled) instead of removed. A batch with no invites sent yet has nothing
        # to preserve, so it's safe to soft-delete outright.
        if Invitation.objects.filter(batch=batch).exists():
            batch.status = Batch.Status.CANCELLED
            batch.save(update_fields=['status'])
            log_action(request, request.user, 'deactivate', 'batch', batch.batch_id)
            return Response({'detail': f'"{batch.batch_name}" has invites already sent, so it has '
                                        f'been deactivated (marked Cancelled) rather than deleted.'})

        batch.is_deleted = True
        batch.save(update_fields=['is_deleted'])
        log_action(request, request.user, 'delete', 'batch', batch.batch_id)
        return Response({'detail': f'"{batch.batch_name}" has been deleted.'})


class BatchDefaultsView(APIView):
    permission_classes = [IsAdminOrTA]

    def get(self, request):
        return Response(get_batch_defaults())

    def put(self, request):
        serializer = BatchDefaultsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        save_batch_defaults(serializer.validated_data, request.user)
        return Response(get_batch_defaults())


class BatchTemplateDownloadView(APIView):
    permission_classes = [IsAdminOrTA]

    def get(self, request):
        wb = generate_template_workbook()
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        response = HttpResponse(
            buffer.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename="candidate_upload_template.xlsx"'
        return response


class BatchUploadView(APIView):
    permission_classes = [IsAdminOrTA]
    parser_classes = [MultiPartParser]

    # A legitimate candidate-upload spreadsheet (a few hundred to a few thousand rows of plain
    # text) is nowhere near this size - anything bigger is either a mistake or someone testing
    # how much memory/CPU stage_candidates_from_workbook's row-by-row parsing can be made to burn.
    MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024

    def post(self, request, batch_id):
        batch = _get_batch_or_404(request.user, batch_id)
        if batch.status != Batch.Status.DRAFT:
            return Response({'detail': 'This batch has already been finalized.'},
                             status=status.HTTP_400_BAD_REQUEST)

        upload = request.FILES.get('file')
        if not upload:
            return Response({'detail': 'No file uploaded.'}, status=status.HTTP_400_BAD_REQUEST)
        if not upload.name.lower().endswith('.xlsx'):
            return Response({'detail': 'Only .xlsx files are supported.'}, status=status.HTTP_400_BAD_REQUEST)
        if upload.size > self.MAX_UPLOAD_SIZE_BYTES:
            return Response(
                {'detail': f'File is too large (max {self.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            cooling_off_months = int(request.data.get('cooling_off_months', 3))
        except (TypeError, ValueError):
            cooling_off_months = 3
        cooling_off_months = max(1, min(cooling_off_months, 24))

        try:
            created = stage_candidates_from_workbook(batch, upload, request.user, cooling_off_months)
        except (zipfile.BadZipFile, InvalidFileException, KeyError, DataError):
            # These specifically indicate a malformed/corrupt/mistyped-data upload (not a valid
            # xlsx container, or a cell value that doesn't fit its column) - genuinely the
            # user's file, not our bug. Anything else propagates as an unhandled 500 so a real
            # defect here doesn't get silently mislabeled as "bad file" and go unnoticed.
            logger.exception('Failed to parse uploaded workbook for batch_id=%s', batch.batch_id)
            return Response(
                {'detail': 'Could not read that file. Make sure it matches the template format.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not created:
            return Response({'detail': 'No data rows found in that file.'}, status=status.HTTP_400_BAD_REQUEST)

        batch.total_candidates = batch.candidate_set.filter(is_deleted=False).count()
        batch.save(update_fields=['total_candidates'])
        log_action(request, request.user, 'upload', 'batch', batch.batch_id,
                   details={'rows_created': len(created)})

        ok_count = sum(1 for c in created if c.validation_status == Candidate.ValidationStatus.OK)
        return Response({
            'rows_created': len(created),
            'ok_count': ok_count,
            'validation_error_count': len(created) - ok_count,
        }, status=status.HTTP_201_CREATED)


class BatchCandidatesStagingView(APIView):
    permission_classes = [IsAdminOrTA]

    def get(self, request, batch_id):
        batch = _get_batch_or_404(request.user, batch_id)
        candidates = (
            batch.candidate_set
            .filter(is_deleted=False)
            .prefetch_related('duplicate_checks', 'duplicate_checks__existing_candidate__batch')
            .order_by('upload_row_number', 'candidate_id')
        )
        return Response(CandidateStagingSerializer(candidates, many=True).data)


class BatchCandidateDeleteView(APIView):
    permission_classes = [IsAdminOrTA]

    def post(self, request, batch_id):
        batch = _get_batch_or_404(request.user, batch_id)
        if Invitation.objects.filter(batch=batch).exists():
            return Response({'detail': 'Cannot remove candidates after invites have been sent.'},
                             status=status.HTTP_400_BAD_REQUEST)
        candidate_ids = request.data.get('candidate_ids', [])
        if not isinstance(candidate_ids, list) or not candidate_ids:
            return Response({'detail': 'candidate_ids must be a non-empty list.'},
                             status=status.HTTP_400_BAD_REQUEST)

        # QuerySet.delete()'s own return value is the TOTAL objects deleted across cascades
        # (each Candidate's DuplicateCheck rows cascade-delete too) - count candidates
        # specifically instead of trusting that number as "candidates deleted".
        to_delete = batch.candidate_set.filter(candidate_id__in=candidate_ids)
        candidate_count = to_delete.count()
        to_delete.delete()
        batch.total_candidates = batch.candidate_set.filter(is_deleted=False).count()
        batch.save(update_fields=['total_candidates'])
        log_action(request, request.user, 'delete_candidates', 'batch', batch.batch_id,
                   details={'candidate_ids': candidate_ids})
        return Response({'deleted_count': candidate_count})


class BatchCandidateClearDuplicateView(APIView):
    permission_classes = [IsAdminOrTA]

    def post(self, request, batch_id, candidate_id):
        batch = _get_batch_or_404(request.user, batch_id)
        try:
            candidate = batch.candidate_set.get(candidate_id=candidate_id, is_deleted=False)
        except Candidate.DoesNotExist:
            raise Http404

        check = clear_duplicate(candidate, request.user)
        if not check:
            return Response({'detail': 'No duplicate check found for this candidate.'},
                             status=status.HTTP_400_BAD_REQUEST)
        return Response(CandidateStagingSerializer(candidate).data)


class BatchFinalizeView(APIView):
    permission_classes = [IsAdminOrTA]

    def post(self, request, batch_id):
        batch = _get_batch_or_404(request.user, batch_id)
        if batch.status != Batch.Status.DRAFT:
            return Response({'detail': 'This batch has already been finalized.'},
                             status=status.HTTP_400_BAD_REQUEST)

        candidates = batch.candidate_set.filter(is_deleted=False)
        total = candidates.count()
        if total == 0:
            return Response({'detail': 'Upload at least one candidate before finalizing.'},
                             status=status.HTTP_400_BAD_REQUEST)

        invalid_count = candidates.exclude(validation_status=Candidate.ValidationStatus.OK).count()
        if invalid_count:
            return Response(
                {'detail': f'{invalid_count} row(s) still have validation errors - fix or remove them first.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        blocking_ids = [
            c.candidate_id for c in candidates.prefetch_related('duplicate_checks')
            if (latest := max(c.duplicate_checks.all(), key=lambda d: d.checked_at, default=None))
            and latest.check_status == DuplicateCheck.CheckStatus.DUPLICATE_WITHIN_WINDOW
        ]
        if blocking_ids:
            return Response(
                {'detail': f'{len(blocking_ids)} row(s) have an unresolved duplicate within the cooling-off '
                            f'window - clear or remove them first.',
                 'candidate_ids': blocking_ids},
                status=status.HTTP_400_BAD_REQUEST,
            )

        batch.status = Batch.Status.IN_PROGRESS
        batch.total_candidates = total
        batch.save(update_fields=['status', 'total_candidates'])
        log_action(request, request.user, 'finalize', 'batch', batch.batch_id)

        return Response({
            'batch_id': batch.batch_id,
            'batch_name': batch.batch_name,
            'college_name': batch.college_name,
            'candidate_count': total,
            'link_valid_from': batch.link_valid_from,
            'link_valid_until': batch.link_valid_until,
            'exam_duration_minutes': batch.exam_duration_minutes,
            'total_questions': (batch.logical_questions + batch.quantitative_questions
                                + batch.verbal_questions + batch.programming_questions),
            'logical_cutoff': batch.logical_cutoff,
            'quantitative_cutoff': batch.quantitative_cutoff,
            'verbal_cutoff': batch.verbal_cutoff,
            'programming_cutoff': batch.programming_cutoff,
        })


class BatchSendInvitesView(APIView):
    permission_classes = [IsAdminOrTA]

    def post(self, request, batch_id):
        batch = _get_batch_or_404(request.user, batch_id)
        if batch.status == Batch.Status.DRAFT:
            return Response({'detail': 'Finalize this batch before sending invites.'},
                             status=status.HTTP_400_BAD_REQUEST)
        if batch.status == Batch.Status.CANCELLED:
            return Response({'detail': 'This batch has been cancelled and can no longer send invites.'},
                             status=status.HTTP_400_BAD_REQUEST)

        invitations = create_invitations(batch, request.user)
        if invitations:
            send_invites_async(invitations, settings.FRONTEND_ORIGIN)
            for invitation in invitations:
                log_action(request, request.user, 'invite_sent', 'candidate', invitation.candidate_id,
                           details={'batch_id': batch.batch_id})

        return Response({
            'invited_count': len(invitations),
            'detail': f'{len(invitations)} invitation(s) queued for sending.' if invitations
                      else 'No pending candidates to invite (already sent, or none uploaded).',
        })
