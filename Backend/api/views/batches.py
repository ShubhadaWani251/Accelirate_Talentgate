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

from api.models import Batch, Candidate, Invitation
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
        # annotate_batch_counts here rather than letting BatchSerializer fall back to its
        # per-instance queries: without it pass_count and fail_count each fire their own
        # COUNT(*), which on a remote database is two extra network round-trips on every
        # batch fetch. The annotation folds them into this same single query.
        batch = annotate_batch_counts(
            Batch.objects.select_related('primary_ta_user')
        ).get(batch_id=batch_id, is_deleted=False)
    except Batch.DoesNotExist:
        raise Http404
    if not can_access_batch(user, batch):
        raise Http404  # don't reveal existence of batches the caller can't access
    return batch


class BatchListCreateView(APIView):
    permission_classes = [IsAdminOrTA]

    def get(self, request):
        # Unscoped by owner on purpose - every TA sees every batch (see services/access.py).
        qs = Batch.objects.select_related('primary_ta_user').filter(is_deleted=False)
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

    # Cutoffs are the one part of a finalized batch that still has to move: results are graded
    # against them, and a TA legitimately revises a cutoff after seeing how a cohort scored.
    # Everything else (dates, question counts, duration) would retroactively invalidate an exam
    # that candidates have already sat, so it stays frozen once the batch leaves Draft.
    EDITABLE_AFTER_DRAFT = {
        'logical_cutoff', 'quantitative_cutoff', 'verbal_cutoff', 'programming_cutoff',
    }

    def patch(self, request, batch_id):
        batch = _get_batch_or_404(request.user, batch_id)
        if batch.status == Batch.Status.CANCELLED:
            return Response({'detail': 'This batch is deactivated; its configuration can no '
                                        'longer be changed.'},
                             status=status.HTTP_400_BAD_REQUEST)

        if batch.status != Batch.Status.DRAFT:
            locked = set(request.data) - self.EDITABLE_AFTER_DRAFT
            if locked:
                return Response(
                    {'detail': 'This batch has been finalized - only the section cutoffs can '
                               'still be changed.',
                     'locked_fields': sorted(locked)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        serializer = BatchSerializer(batch, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        log_action(request, request.user, 'update', 'batch', batch.batch_id)
        return Response(serializer.data)


class BatchDeactivateView(APIView):
    """Deactivation, not deletion: the batch row and all its candidate/result history stay
    intact and simply stop accepting invites. Batches are never removed - a TA who has sent
    invites can't un-send them, and results already recorded against a batch are the record
    of what happened.
    """
    permission_classes = [IsAdminOrTA]

    def post(self, request, batch_id):
        batch = _get_batch_or_404(request.user, batch_id)
        if batch.status == Batch.Status.CANCELLED:
            return Response({'detail': 'This batch is already deactivated.'},
                             status=status.HTTP_400_BAD_REQUEST)

        batch.status = Batch.Status.CANCELLED
        batch.save(update_fields=['status'])
        log_action(request, request.user, 'deactivate', 'batch', batch.batch_id)
        return Response({
            'detail': f'"{batch.batch_name}" has been deactivated. Its candidates and results '
                      f'are still available, but no further invites can be sent.',
            'batch': BatchSerializer(batch).data,
        })


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

        # The reviewer's checkbox selection IS the invite list. Rows they deliberately left
        # unchecked (a duplicate inside the cooling-off window, say) stay on the batch as an
        # uploaded record but are never emailed - so there's no separate "clear the duplicate
        # flag" step to unblock finalizing any more. Selecting the row is that decision.
        candidate_ids = request.data.get('candidate_ids')
        if not isinstance(candidate_ids, list) or not candidate_ids:
            return Response(
                {'detail': 'Select at least one candidate to invite before creating the batch.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        selected = list(candidates.filter(candidate_id__in=candidate_ids))
        if not selected:
            return Response({'detail': 'None of the selected candidates belong to this batch.'},
                             status=status.HTTP_400_BAD_REQUEST)

        # Only the selected rows have to be valid - an unselected row with a missing email is
        # fine, precisely because it's not going to be emailed.
        invalid = [c for c in selected if c.validation_status != Candidate.ValidationStatus.OK]
        if invalid:
            return Response(
                {'detail': f'{len(invalid)} selected row(s) still have validation errors - '
                            f'uncheck or remove them first.',
                 'candidate_ids': [c.candidate_id for c in invalid]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        batch.status = Batch.Status.IN_PROGRESS
        batch.total_candidates = total
        batch.save(update_fields=['status', 'total_candidates'])
        log_action(request, request.user, 'finalize', 'batch', batch.batch_id,
                   details={'selected_count': len(selected), 'uploaded_count': total})

        # Finalizing creates the batch but sends nothing. The wireframe makes the summary on
        # "Send Invite - Confirmation" a mandatory pre-dispatch step, so the selected ids are
        # handed back for that screen to post to send-invites once the TA confirms.
        selected_ids = [c.candidate_id for c in selected]

        return Response({
            'batch_id': batch.batch_id,
            'batch_name': batch.batch_name,
            'college_name': batch.college_name,
            'candidate_count': total,
            'selected_candidate_ids': selected_ids,
            'selected_count': len(selected_ids),
            'skipped_count': total - len(selected_ids),
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

        # Invites are always sent to an explicit selection - never "everyone still pending".
        # A blanket send would sweep up rows the reviewer deliberately skipped (a duplicate
        # inside the cooling-off window, say) and silently undo that decision.
        candidate_ids = request.data.get('candidate_ids')
        if not isinstance(candidate_ids, list) or not candidate_ids:
            return Response({'detail': 'Select the candidates to invite first.'},
                             status=status.HTTP_400_BAD_REQUEST)

        invitations = create_invitations(batch, request.user, candidate_ids=candidate_ids)
        if invitations:
            send_invites_async(invitations, settings.FRONTEND_ORIGIN)
            for invitation in invitations:
                log_action(request, request.user, 'invite_sent', 'candidate', invitation.candidate_id,
                           details={'batch_id': batch.batch_id})

        skipped = len(candidate_ids) - len(invitations)
        detail = f'{len(invitations)} invitation(s) queued for sending.'
        if not invitations:
            detail = ('No invitations sent - the selected candidate(s) have already been '
                      'invited, or have unresolved validation errors.')
        elif skipped > 0:
            detail += f' {skipped} already invited, so skipped.'

        return Response({'invited_count': len(invitations), 'skipped_count': max(skipped, 0),
                         'detail': detail})
