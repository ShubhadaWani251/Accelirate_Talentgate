import logging

from django.db import DataError
from django.http import Http404, HttpResponse
from django.db.models import Q
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
from api.services.question_bank import generate_question_template_workbook, import_questions_from_workbook

logger = logging.getLogger(__name__)


def _get_question_or_404(question_id):
    try:
        return Question.objects.select_related('section').get(question_id=question_id)
    except Question.DoesNotExist:
        raise Http404


class QuestionSectionListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        sections = QuestionBankSection.objects.all()
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

        qs = qs.order_by('question_code')
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

        try:
            created, errors = import_questions_from_workbook(upload, request.user)
        except (zipfile.BadZipFile, InvalidFileException, KeyError, DataError):
            logger.exception('Failed to parse uploaded question workbook')
            return Response(
                {'detail': 'Could not read that file. Make sure it matches the template format.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not created and not errors:
            return Response({'detail': 'No data rows found in that file.'}, status=status.HTTP_400_BAD_REQUEST)

        log_action(request, request.user, 'bulk_upload', 'question', 0,
                   details={'created_count': len(created), 'error_count': len(errors)})

        return Response({
            'created_count': len(created),
            'error_count': len(errors),
            'errors': errors,
        }, status=status.HTTP_201_CREATED)
