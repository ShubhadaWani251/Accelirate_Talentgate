import logging

from django.db import DataError
from django.http import Http404, HttpResponse
from django.db.models import Count, F, Q, Window
from django.db.models.functions import RowNumber
from openpyxl.utils.exceptions import InvalidFileException
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
import zipfile

from api.models import Question, QuestionBankSection, Setting
from api.pagination import StandardResultsPagination
from api.permissions import IsAdmin, IsAdminOrTA
from api.serializers.question import (
    QuestionBankSectionSerializer, QuestionSerializer, SectionCreateSerializer,
)
from api.services import batch_defaults
from api.services.audit import log_action
from api.services.question_bank import (
    generate_question_template_workbook,
    validate_question_rows,
    validate_question_workbook,
)

logger = logging.getLogger(__name__)


def _get_question_or_404(question_id):
    try:
        return Question.objects.select_related('section').get(question_id=question_id)
    except Question.DoesNotExist:
        raise Http404


def _sections_with_counts():
    """Sections, each carrying its own total / active / inactive question counts.

    Counted here rather than in the browser because the question list is paginated - the
    frontend only ever holds one page, so it cannot total a section from what it has. One
    aggregate query with conditional Counts, not three queries per section.
    """
    return QuestionBankSection.objects.annotate(
        total_questions=Count('question'),
        active_questions=Count('question', filter=Q(question__status=Question.Status.ACTIVE)),
        inactive_questions=Count(
            'question', filter=Q(question__status=Question.Status.INACTIVE)
        ),
        # order_by is REQUIRED here, not decoration: annotate() folds a model's Meta.ordering
        # into the GROUP BY, which reorders the result - this endpoint was returning logical,
        # verbal, quantitative, programming instead of the configured 0,1,2,3. Restating it
        # explicitly is Django's own documented way out of that.
    ).order_by('display_order', 'section_name')


class QuestionSectionListView(APIView):
    def get_permissions(self):
        """Reading the section list is IsAdminOrTA; adding one is IsAdmin.

        A TA needs the list to render All Candidates at all - the score columns are one per
        section now, so without it the table has no headers. The list carries nothing sensitive
        (section names and question counts), unlike the question bank itself, which stays
        admin-only in every other view on this screen.
        """
        return [IsAdminOrTA()] if self.request.method == 'GET' else [IsAdmin()]

    def get(self, request):
        return Response(QuestionBankSectionSerializer(_sections_with_counts(), many=True).data)

    def post(self, request):
        """Add a section. Admin-only, like every other write on this screen.

        A new section is immediately available to every NEW batch, appears as its own column in
        the All Candidates and Batch Details tables and in the Excel export, and gets its own
        card on this screen - all without a code change, because nothing downstream names
        sections any more. It does NOT touch existing batches: those are snapshotted at creation
        (see models.BatchSection), so a drive already underway is never reshaped underneath its
        candidates.
        """
        serializer = SectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        section = serializer.save()
        log_action(request, request.user, 'create', 'question_section', section.section_id,
                   details={'section_name': section.section_name,
                            'section_key': section.section_key})
        return Response(
            QuestionBankSectionSerializer(
                _sections_with_counts().get(pk=section.pk),
            ).data,
            status=status.HTTP_201_CREATED,
        )


class QuestionSectionDetailView(APIView):
    """Delete or restore one section. Admin-only.

    Deleting a section means one thing: it stops appearing in any NEW batch, and every batch that
    already ran it - along with every score recorded under it - is left exactly as it was. A
    candidate's result has to keep describing the exam they actually sat.

    That single promise is delivered two ways, depending on whether there is any history to keep:

      - Nothing depends on the section (no questions, no batch ever used it): the row is removed
        outright. There is no past to preserve and a tombstone would just be clutter.
      - Anything does depend on it: the row is RETIRED (is_active=False) instead. Question,
        BatchSection and AttemptSectionScore all reference it with PROTECT, so a real delete
        would have to either take the question bank's content with it or rewrite what a cohort
        was assessed on.

    The response says which happened, but the admin is never asked to choose - from their side
    it is one action with one meaning.
    """
    permission_classes = [IsAdmin]

    def _get_or_404(self, section_id):
        try:
            return QuestionBankSection.objects.get(pk=section_id)
        except QuestionBankSection.DoesNotExist:
            raise Http404

    def delete(self, request, section_id):
        section = self._get_or_404(section_id)
        name, key = section.section_name, section.section_key

        question_count = section.question_set.count()
        batch_count = section.batch_sections.values('batch_id').distinct().count()

        if question_count or batch_count:
            section.is_active = False
            section.save(update_fields=['is_active'])
            # Drafts follow the defaults (see batch_defaults.resync_draft_batches), and this
            # section has just left them - so it has to leave the drafts too, or a draft created
            # this morning would still run a section that no longer exists anywhere else.
            batch_defaults.resync_draft_batches()
            log_action(request, request.user, 'update', 'question_section', section_id,
                       details={'section_name': name, 'retired': True,
                                'question_count': question_count, 'batch_count': batch_count})
            kept = []
            if question_count:
                kept.append(f'{question_count} question{"" if question_count == 1 else "s"}')
            if batch_count:
                kept.append(f'{batch_count} batch{"" if batch_count == 1 else "es"}')
            return Response({
                'removed': False,
                'detail': f'"{name}" will not appear in any new batch. Its '
                          f'{" and ".join(kept)} already using it are unchanged.',
                'question_count': question_count,
                'batch_count': batch_count,
            })

        section.delete()
        # The section's own defaults rows go with it, or they would sit in the Setting table
        # forever and silently reapply if a section with the same derived key were added later.
        Setting.objects.filter(
            setting_group=batch_defaults.SETTING_GROUP,
            setting_key__startswith=f'{batch_defaults.SETTING_GROUP}.section.{key}.',
        ).delete()
        log_action(request, request.user, 'delete', 'question_section', section_id,
                   details={'section_name': name, 'section_key': key})
        return Response({'removed': True, 'detail': f'"{name}" deleted.'})

    def patch(self, request, section_id):
        """Retire (is_active=False) or restore a section.

        A retired section disappears from Configure Default Batch and never reaches a new batch,
        while every batch that already ran it, and every score recorded under it, stays exactly
        as it was. This is the answer for a section that can no longer be deleted.
        """
        section = self._get_or_404(section_id)
        is_active = request.data.get('is_active')
        if not isinstance(is_active, bool):
            return Response({'is_active': 'Send true or false.'},
                             status=status.HTTP_400_BAD_REQUEST)

        section.is_active = is_active
        section.save(update_fields=['is_active'])
        # Same reason as the delete path above - a draft has had nothing sent to its candidates,
        # so it tracks whatever the org currently runs.
        batch_defaults.resync_draft_batches()
        log_action(request, request.user, 'update', 'question_section', section.section_id,
                   details={'section_name': section.section_name, 'is_active': is_active})
        return Response(
            QuestionBankSectionSerializer(_sections_with_counts().get(pk=section.pk)).data,
        )


class QuestionListCreateView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = Question.objects.select_related('section').all()

        section_key = request.query_params.get('section', '').strip()
        if section_key:
            qs = qs.filter(section__section_key=section_key)

        difficulty = request.query_params.get('difficulty', '').strip()
        if difficulty:
            qs = qs.filter(difficulty=difficulty)

        q_status = request.query_params.get('status', '').strip()
        if q_status:
            qs = qs.filter(status=q_status)

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(question_code__icontains=search) | Q(question_text__icontains=search)
                | Q(option_a__icontains=search) | Q(option_b__icontains=search)
                | Q(option_c__icontains=search) | Q(option_d__icontains=search)
            )

        # Number each question 1..n WITHIN its section, rather than showing the global
        # question_code as the position. A window function rather than enumerating the page:
        # the number has to be the question's absolute position in its section, so page 2 must
        # continue from where page 1 stopped instead of restarting at 1.
        #
        # Deliberately computed here and not stored: a per-section counter column would have to
        # be renumbered every time a question is added, deleted or moved between sections, and
        # would silently develop gaps the first time that failed.
        qs = qs.annotate(
            section_number=Window(
                expression=RowNumber(),
                partition_by=[F('section_id')],
                order_by=F('question_id').asc(),
            )
        ).order_by('section__section_name', 'section_number')
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(QuestionSerializer(page, many=True).data)

    def post(self, request):
        serializer = QuestionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.save(created_by=request.user)
        log_action(request, request.user, 'create', 'question', question.question_id)
        return Response(QuestionSerializer(question).data, status=status.HTTP_201_CREATED)


class QuestionDetailView(APIView):
    permission_classes = [IsAdmin]

    def patch(self, request, question_id):
        question = _get_question_or_404(question_id)
        serializer = QuestionSerializer(question, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        log_action(request, request.user, 'update', 'question', question.question_id)
        return Response(serializer.data)


class QuestionTemplateDownloadView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        wb = generate_question_template_workbook()
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename="question_upload_template.xlsx"'
        wb.save(response)
        return response


class QuestionRowValidationView(APIView):
    """Re-validate (and optionally import) rows edited on the Question Validation screen.

    Backs per-field correction: the reviewer fixes a bad section name or correct-answer letter
    and the edited rows come back here rather than forcing a spreadsheet re-upload. Import runs
    the identical validation, so a row edited into an invalid state - or posted directly to the
    API - still cannot be written to the bank.
    """
    permission_classes = [IsAdmin]

    def post(self, request):
        raw_rows = request.data.get('rows')
        if not isinstance(raw_rows, list) or not raw_rows:
            return Response({'detail': 'rows must be a non-empty list.'},
                             status=status.HTTP_400_BAD_REQUEST)

        validate_only = bool(request.data.get('validate_only', True))
        rows, summary = validate_question_rows(raw_rows, user=request.user, dry_run=validate_only)

        if not validate_only and summary['valid'] == 0:
            return Response({'detail': 'No valid questions to import.'},
                             status=status.HTTP_400_BAD_REQUEST)

        by_section = {}
        for row in rows:
            if row['status'] == 'valid':
                by_section[row['section_name']] = by_section.get(row['section_name'], 0) + 1

        if not validate_only:
            log_action(request, request.user, 'bulk_upload', 'question', 0,
                       details={'created_count': summary['valid'],
                                'invalid_count': summary['invalid'],
                                'duplicate_count': summary['duplicate'],
                                'sections': by_section, 'source': 'edited_rows'})

        return Response({
            'validate_only': validate_only,
            'summary': summary,
            'rows': rows,
            'by_section': by_section,
            'created_count': 0 if validate_only else summary['valid'],
        }, status=status.HTTP_200_OK if validate_only else status.HTTP_201_CREATED)


class QuestionBulkUploadView(APIView):
    permission_classes = [IsAdmin]
    parser_classes = [MultiPartParser]

    # Same reasoning as BatchUploadView.MAX_UPLOAD_SIZE_BYTES - a legitimate question sheet
    # (plain text, a few hundred/thousand rows) is nowhere near this size.
    MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024

    def post(self, request):
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

        # Two-phase: the UI validates first (validate_only=true) and shows the results table,
        # then imports the same file. The import re-reads and re-validates from scratch rather
        # than trusting the reviewed payload, so nothing invalid can be posted back in.
        validate_only = str(request.data.get('validate_only', '')).lower() in ('1', 'true', 'yes')

        try:
            rows, summary = validate_question_workbook(
                upload, user=request.user, dry_run=validate_only,
            )
        except (zipfile.BadZipFile, InvalidFileException, KeyError, DataError):
            logger.exception('Failed to parse uploaded question workbook')
            return Response(
                {'detail': 'Could not read that file. Make sure it matches the template format.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not rows:
            return Response({'detail': 'No data rows found in that file.'},
                             status=status.HTTP_400_BAD_REQUEST)

        # Section counts let the UI show what a multi-section sheet actually resolved to, so a
        # misfiled row is obvious before anything is written.
        by_section = {}
        for row in rows:
            if row['status'] == 'valid':
                by_section[row['section_name']] = by_section.get(row['section_name'], 0) + 1

        if not validate_only:
            log_action(request, request.user, 'bulk_upload', 'question', 0,
                       details={'created_count': summary['valid'],
                                'invalid_count': summary['invalid'],
                                'duplicate_count': summary['duplicate'],
                                'sections': by_section})

        return Response({
            'validate_only': validate_only,
            'summary': summary,
            'rows': rows,
            'by_section': by_section,
            'created_count': 0 if validate_only else summary['valid'],
        }, status=status.HTTP_200_OK if validate_only else status.HTTP_201_CREATED)
