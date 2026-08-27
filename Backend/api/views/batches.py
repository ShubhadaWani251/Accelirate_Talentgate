import io
import logging
import zipfile

from django.db import DataError, transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from openpyxl.utils.exceptions import InvalidFileException
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Batch, Candidate, Invitation
from api.pagination import StandardResultsPagination
from api.permissions import IsAdmin, IsAdminOrTA
from api.serializers.batch import (
    BatchDefaultsSerializer, BatchSerializer, CandidateStagingSerializer, annotate_batch_counts,
    link_window_error,
)
from api.services.access import can_access_batch, visible_batches_qs
from api.services.audit import log_action
from api.services.batch_defaults import get_batch_defaults, save_batch_defaults
from api.services.batch_status_filter import filter_batches_by_status_group
from api.services import draft_expiry
from api.services.candidate_validation import (
    EDITABLE_FIELDS, clamp_aadhaar_to_last4, revalidate_batch_candidates, summarize_candidates,
)
from api.services import exam_session
from api.services.duplicate_check import clear_duplicate, run_duplicate_check
from api.services.excel_upload import (
    generate_template_workbook, generate_validation_report_workbook,
    stage_candidates_from_workbook,
)
from api.services.invites import (
    BatchNotInvitableError, assert_batch_can_invite, create_invitations,
)

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

    # A Draft has 24 hours to be finalized (services/draft_expiry.py). Every batch-scoped
    # endpoint routes through this function, so one check here is what stops a stale
    # frontend - or a hand-rolled request - from reading, editing, uploading to, adding
    # candidates to, finalizing or inviting from an expired draft. It's deleted on contact
    # rather than just refused, so an expired draft that the scheduler hasn't reached yet
    # doesn't survive being touched.
    if draft_expiry.delete_if_expired(batch):
        raise Http404
    return batch


class BatchListCreateView(APIView):
    permission_classes = [IsAdminOrTA]

    def get(self, request):
        # Scoped to batches this user may see - own batches for a TA, all of them for an
        # admin (services/access.visible_batches_qs). Routed through the same helper
        # can_access_batch uses, so the list and the detail page can never disagree about
        # which batches exist.
        #
        # Expired drafts are dropped so the list is right the instant one expires rather than
        # at the next scheduler tick; the deletion itself happens in draft_expiry, not here.
        qs = draft_expiry.exclude_expired(
            visible_batches_qs(request.user).select_related('primary_ta_user')
        )

        # Unified Batch Status filter - 'active' (In Progress + Completed) by default, or
        # 'draft' / 'cancelled' / 'all' on request. Same grouping the dashboard uses, via the
        # shared helper, so "Active" means the same set of statuses in both places.
        qs = filter_batches_by_status_group(qs, request.query_params.get('status'))

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(Q(batch_name__icontains=search) | Q(college_name__icontains=search))
        qs = annotate_batch_counts(qs.order_by('-created_at'))
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(BatchSerializer(page, many=True).data)

    def post(self, request):
        # Only batch_name and college_name come from the request now - the exam schedule,
        # question counts and cutoffs are the admin-configured org-wide defaults
        # (services/batch_defaults.py), snapshotted onto this batch at creation via the
        # explicit kwargs below. Passed as save() kwargs rather than left to the serializer's
        # own (now read-only, for 5 of these 9 fields - see BatchSerializer.Meta) field handling
        # specifically so this is unconditional: kwargs always win over whatever validated_data
        # holds, so even a request that also supplied its own values for the 4 still-writable
        # cutoff fields gets the current defaults instead. A batch's configuration should never
        # depend on what a particular create request happened to send.
        serializer = BatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        batch = serializer.save(
            primary_ta_user=request.user,
            created_by=request.user,
            status=Batch.Status.DRAFT,
            **get_batch_defaults(),
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

        # Cutoffs grade results, so revising one is a policy call, not a data-entry fix - kept
        # admin-only even though a TA can otherwise PATCH this same endpoint (e.g. the wizard's
        # own link-window step, which never touches these fields).
        if self.EDITABLE_AFTER_DRAFT & set(request.data) and request.user.role.role_code != 'admin':
            return Response(
                {'detail': 'Only an admin can change section cutoffs.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if batch.status != Batch.Status.DRAFT:
            locked = set(request.data) - self.EDITABLE_AFTER_DRAFT
            if locked:
                return Response(
                    {'detail': 'This batch has been finalized - only the section cutoffs can '
                               'still be changed.',
                     'locked_fields': sorted(locked)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        cutoffs_before = {f: getattr(batch, f) for f in self.EDITABLE_AFTER_DRAFT}

        serializer = BatchSerializer(batch, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        batch = serializer.save()
        log_action(request, request.user, 'update', 'batch', batch.batch_id)

        # Results are graded against the cutoffs, so changing one has to re-grade the candidates
        # already scored under the old value - otherwise Batch Details and Candidate Details keep
        # showing pass/fail computed at submit time, which no longer matches the batch config.
        cutoffs_changed = any(
            getattr(batch, f) != cutoffs_before[f] for f in self.EDITABLE_AFTER_DRAFT
        )
        data = serializer.data
        if cutoffs_changed:
            regraded = exam_session.regrade_batch(batch)
            data = {**data, 'regraded_candidates': regraded}

        return Response(data)


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


class BatchCompleteView(APIView):
    """Manually marks a batch Completed. Nothing in the app infers this automatically - see
    services/batch_status_filter.py, which already groups Completed alongside In Progress under
    "Active" precisely because nothing ever produced a Completed batch until this. A TA/admin
    decides when a drive is actually done: "every candidate finished" doesn't account for
    stragglers written off, and "the link window closed" doesn't account for a TA who
    deliberately keeps inviting past it.
    """
    permission_classes = [IsAdminOrTA]

    def post(self, request, batch_id):
        batch = _get_batch_or_404(request.user, batch_id)
        if batch.status != Batch.Status.IN_PROGRESS:
            return Response(
                {'detail': 'Only an in-progress batch can be marked completed.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        batch.status = Batch.Status.COMPLETED
        batch.save(update_fields=['status'])
        log_action(request, request.user, 'complete', 'batch', batch.batch_id)
        return Response({
            'detail': f'"{batch.batch_name}" has been marked completed.',
            'batch': BatchSerializer(batch).data,
        })


class BatchDefaultsView(APIView):
    """Reads/writes the org-wide default exam configuration new batches are created
    with. Admin-only: this affects every batch anyone creates from here on, which is a bigger
    blast radius than any single TA's own work and shouldn't be changeable from inside the
    upload wizard the way it used to be - see services/batch_defaults.py.
    """
    permission_classes = [IsAdmin]

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
            created, missing_columns, staged, skipped_duplicates = stage_candidates_from_workbook(
                batch, upload, request.user, cooling_off_months,
            )
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
            # Every parsed row lands in exactly one of these two lists (see
            # stage_candidates_from_workbook), so an empty `created` with a non-empty
            # `skipped_duplicates` means the file had real rows - they just all matched a
            # candidate already staged on this batch (dedup is seeded from the batch's existing
            # rows specifically so a second file added to the same draft collapses against the
            # first). That is a completely different situation from an empty/unreadable file,
            # and "no data rows found" told the uploader the wrong thing about their own file -
            # most commonly hit by going back to Upload and picking the same file again.
            if skipped_duplicates:
                return Response(
                    {'detail': f'Every row in this file matches a candidate already on this '
                               f'batch ({len(skipped_duplicates)} duplicate(s) skipped) - '
                               f'nothing new to add. Upload a different file, or continue to '
                               f'the candidates already staged.',
                     'skipped_duplicates': skipped_duplicates},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response({'detail': 'No data rows found in that file.'}, status=status.HTTP_400_BAD_REQUEST)

        batch.total_candidates = len(staged)
        batch.save(update_fields=['total_candidates'])
        log_action(request, request.user, 'upload', 'batch', batch.batch_id,
                   details={'rows_created': len(created), 'missing_columns': missing_columns,
                            'duplicates_skipped': len(skipped_duplicates)})

        summary = summarize_candidates(staged)
        return Response({
            'rows_created': len(created),
            'ok_count': summary['valid'],
            'validation_error_count': summary['invalid'],
            'summary': summary,
            # Named so the review screen can say "this sheet has no Aadhaar Number column"
            # instead of showing every row as missing it and leaving the reviewer to guess.
            'missing_columns': missing_columns,
            # Repeated entries collapsed to one. Reported rather than silent: the reviewer
            # should know their 40-row sheet became 38 candidates, and why.
            'skipped_duplicates': skipped_duplicates,
        }, status=status.HTTP_201_CREATED)


def _staging_queryset(batch):
    return (
        batch.candidate_set
        .filter(is_deleted=False)
        .prefetch_related('duplicate_checks', 'duplicate_checks__existing_candidate__batch')
        .order_by('upload_row_number', 'candidate_id')
    )


def _staging_payload(batch):
    """The whole review table plus its summary counts.

    Every response that changes a row returns the FULL set rather than just the row touched:
    one correction can flip another row's verdict (fixing a mistyped address can turn a
    later row into a duplicate of it, or clear one), so returning a single row would leave
    the rest of the table - and the counts above it - showing stale results.
    """
    candidates = list(_staging_queryset(batch))
    return {
        'rows': CandidateStagingSerializer(candidates, many=True).data,
        'summary': summarize_candidates(candidates),
    }


class BatchCandidatesStagingView(APIView):
    permission_classes = [IsAdminOrTA]

    def get(self, request, batch_id):
        batch = _get_batch_or_404(request.user, batch_id)
        if batch.status == Batch.Status.DRAFT:
            # A draft uploaded before per-field validation existed carries only the old
            # single-error status and an empty error list, which would render as a red row
            # with nothing in the Errors column. Re-checking on read makes the screen
            # self-correcting; revalidate_batch_candidates only writes rows whose verdict
            # actually moved, so for an up-to-date batch this costs nothing. Drafts only -
            # a finalized batch keeps the verdicts it was finalized under.
            revalidate_batch_candidates(batch)
        return Response(_staging_payload(batch))


class BatchCandidateRowView(APIView):
    """Correct one uploaded row in place, on the Upload Review screen.

    Editing here rather than in the spreadsheet is the point of the validation step: a
    mistyped address or a missing college shouldn't cost a re-upload. Saving re-runs the
    identical validation the upload ran, so a row cannot be edited into a state the upload
    itself would have rejected - and the finalize gate reads the same stored result, so
    nothing invalid reaches the batch even if this endpoint is called directly.
    """
    permission_classes = [IsAdminOrTA]

    def patch(self, request, batch_id, candidate_id):
        batch = _get_batch_or_404(request.user, batch_id)
        if batch.status != Batch.Status.DRAFT:
            return Response({'detail': 'This batch has already been finalized; its candidates '
                                       'can no longer be edited.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            candidate = batch.candidate_set.get(candidate_id=candidate_id, is_deleted=False)
        except Candidate.DoesNotExist:
            raise Http404

        original_aadhaar = candidate.aadhaar_last4
        updates = []
        for field in EDITABLE_FIELDS:
            if field not in request.data:
                continue
            value = request.data[field]
            value = value.strip() if isinstance(value, str) else value

            if field == 'aadhaar_last4':
                if not value:
                    # A blank Aadhaar box means "leave it as it is" - not "erase it". Clearing it
                    # deliberately isn't something the review screen needs to support, and the
                    # field is required for a row to validate.
                    continue
                # Same reason as excel_upload.py's identical clamp: this writes straight to the
                # ORM (setattr + save below), bypassing any serializer-level max_length check, so
                # a reviewer pasting a full Aadhaar number here would otherwise hit a raw
                # DataError from Postgres instead of a normal validation message.
                value = clamp_aadhaar_to_last4(value)
            if field in ('percentage', 'passing_out_year'):
                # Record what was actually typed as well as the parsed value: "abc" parses to
                # None, and without the raw text the reviewer would be told the field is empty
                # rather than that it isn't a number.
                raw = candidate.upload_raw if isinstance(candidate.upload_raw, dict) else {}
                candidate.upload_raw = {**raw, field: '' if value is None else str(value)}
                if 'upload_raw' not in updates:
                    updates.append('upload_raw')
                value = _to_number(value, field)
            elif field in ('last_name', 'phone', 'college_name', 'degree', 'stream', 'location'):
                value = value or None

            setattr(candidate, field, value)
            updates.append(field)

        if not updates:
            return Response({'detail': 'No editable fields were supplied.'},
                            status=status.HTTP_400_BAD_REQUEST)

        candidate.save(update_fields=updates)

        # A corrected Aadhaar suffix (or name) makes this a different person as far as the
        # duplicate history goes, so the previous check's verdict no longer describes this row.
        # See services/candidate_validation.identity_key for what "the same person" means now.
        if candidate.aadhaar_last4 != original_aadhaar:
            run_duplicate_check(candidate)

        revalidate_batch_candidates(batch)
        log_action(request, request.user, 'update', 'candidate', candidate.candidate_id,
                   details={'batch_id': batch.batch_id, 'fields': updates})
        return Response(_staging_payload(batch))


def _to_number(value, field):
    if value in (None, ''):
        return None
    try:
        return int(float(value)) if field == 'passing_out_year' else float(value)
    except (TypeError, ValueError):
        # Neither field is validated by candidate_validation (they're optional and not used
        # for anything gating), so an unparseable value is dropped rather than rejected.
        return None


class BatchValidationReportView(APIView):
    """Download the rows that failed validation, with their errors, as .xlsx.

    The reviewer usually isn't the person who produced the sheet - this is what gets sent
    back to whoever did.
    """
    permission_classes = [IsAdminOrTA]

    def get(self, request, batch_id):
        batch = _get_batch_or_404(request.user, batch_id)
        invalid = [c for c in _staging_queryset(batch)
                   if c.validation_status != Candidate.ValidationStatus.OK]
        wb = generate_validation_report_workbook(invalid)
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        response = HttpResponse(
            buffer.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = (
            f'attachment; filename="batch-{batch.batch_id}-validation-errors.xlsx"'
        )
        return response


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

        # Re-validate what's left and hand the whole table back: removing a row changes other
        # rows' verdicts (delete one of a duplicated pair and its twin is no longer a
        # duplicate), so the caller needs the refreshed set, not just a count.
        revalidate_batch_candidates(batch)
        return Response({'deleted_count': candidate_count, **_staging_payload(batch)})


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
        if batch.status == Batch.Status.CANCELLED:
            return Response(
                {'detail': 'This batch has been cancelled. New candidates cannot be processed '
                           'or invited for this batch.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if batch.status != Batch.Status.DRAFT:
            return Response({'detail': 'This batch has already been finalized.'},
                             status=status.HTTP_400_BAD_REQUEST)

        # Re-run validation from scratch here rather than trusting what the review screen last
        # stored. This is the gate that keeps invalid records out of a live batch, so it has to
        # hold for a caller that never opened that screen at all.
        all_candidates = revalidate_batch_candidates(batch)
        total = len(all_candidates)
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

        # Filtered in Python against the just-revalidated list rather than re-querying, so the
        # rows checked below carry the verdicts that were just computed.
        wanted = {int(cid) for cid in candidate_ids if str(cid).lstrip('-').isdigit()}
        selected = [c for c in all_candidates if c.candidate_id in wanted]
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

        # The assessment link window is set on the wizard's "Review & Send Invite" step (a PATCH
        # to this batch), not at creation any more - a batch's link_valid_from/until can
        # genuinely still be null here if that PATCH was skipped, or has already been through it
        # if the frontend called it first as intended. Checked here regardless: this is the last
        # point before invites can go out, and it must not trust an earlier step to have run.
        if not (batch.link_valid_from and batch.link_valid_until):
            return Response(
                {'detail': "Set the assessment link's valid-from and valid-until dates before "
                           "sending invites."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        window_error = link_window_error(
            batch.link_valid_from, batch.link_valid_until, batch.exam_duration_minutes,
        )
        if window_error:
            return Response({'detail': window_error}, status=status.HTTP_400_BAD_REQUEST)

        # Activation and the draft-expiry sweep can reach the same row at the same moment, and
        # the two must not both win. Taking the row lock and re-reading status/created_at
        # inside it makes this the single atomic decision point: if the cleanup committed its
        # delete first this finds the row gone (or, having crossed 24 hours mid-request, still
        # a Draft that is now expired) and refuses; if this commits first, the cleanup's own
        # locked re-check sees IN_PROGRESS and skips the batch. The checks above stay for their
        # clearer messages - this is the one that's authoritative.
        outcome = 'ok'
        with transaction.atomic():
            locked = Batch.objects.select_for_update().filter(batch_id=batch.batch_id).first()
            if locked is None:
                outcome = 'gone'
            elif locked.status != Batch.Status.DRAFT:
                outcome = 'finalized'
            elif draft_expiry.is_draft_expired(locked):
                outcome = 'expired'
            else:
                locked.status = Batch.Status.IN_PROGRESS
                locked.total_candidates = total
                locked.save(update_fields=['status', 'total_candidates'])

        if outcome == 'expired':
            # Deleted after the lock is released, not inside the block above - raising Http404
            # from inside an atomic block rolls that block back, which would undo the delete.
            draft_expiry.delete_if_expired(locked)
            raise Http404
        if outcome == 'gone':
            raise Http404
        if outcome == 'finalized':
            return Response({'detail': 'This batch has already been finalized.'},
                             status=status.HTTP_400_BAD_REQUEST)

        batch.status = Batch.Status.IN_PROGRESS
        batch.total_candidates = total
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
        # Checked up front so a Draft/Cancelled batch is reported as such rather than as
        # "select the candidates first". services/invites.py owns which statuses may invite and
        # the exact wording, and enforces it again at Invitation creation - this is the same
        # rule, applied early for a clearer message, not a second copy of it.
        try:
            assert_batch_can_invite(batch)
        except BatchNotInvitableError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # Invites are always sent to an explicit selection - never "everyone still pending".
        # A blanket send would sweep up rows the reviewer deliberately skipped (a duplicate
        # inside the cooling-off window, say) and silently undo that decision.
        candidate_ids = request.data.get('candidate_ids')
        if not isinstance(candidate_ids, list) or not candidate_ids:
            return Response({'detail': 'Select the candidates to invite first.'},
                             status=status.HTTP_400_BAD_REQUEST)

        # Only queues them (email_status=QUEUED) - management/commands/process_email_queue.py is
        # what actually sends, on its own schedule. See that command's module docstring for why
        # nothing sends inline from this request any more.
        invitations = create_invitations(batch, request.user, candidate_ids=candidate_ids)
        if invitations:
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
