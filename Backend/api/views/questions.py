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

from api.models import Question, QuestionBankSection
from api.pagination import StandardResultsPagination
from api.permissions import IsAdmin
from api.serializers.question import QuestionBankSectionSerializer, QuestionSerializer
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


class QuestionSectionListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        """Sections, each carrying its own total / active / inactive question counts.

        Counted here rather than in the browser because the question list is paginated - the
        frontend only ever holds one page, so it cannot total a section from what it has. One
        aggregate query with conditional Counts, not three queries per section.
        """
        sections = QuestionBankSection.objects.annotate(
            total_questions=Count('question'),
            active_questions=Count('question', filter=Q(question__status=Question.Status.ACTIVE)),
            inactive_questions=Count(
                'question', filter=Q(question__status=Question.Status.INACTIVE)
            ),
        )
        return Response(QuestionBankSectionSerializer(sections, many=True).data)


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
