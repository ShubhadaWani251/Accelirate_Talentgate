import secrets

from django.conf import settings
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Question
from api.serializers.question import QuestionSerializer
from api.services.audit import log_action
from api.utils.net import ratelimit_ip_key


def _valid_api_key(request):
    configured = (settings.QUESTION_EXPORT_API_KEY or '').strip()
    if not configured:
        # Unset means the integration hasn't been provisioned for this environment - refuse
        # every request rather than falling open, which an empty-string comparison would do.
        return False
    provided = request.META.get('HTTP_X_API_KEY', '')
    # Constant-time: a plain `==` leaks the key one byte at a time through response-time
    # differences, the same reason Django's own password checks avoid it.
    return secrets.compare_digest(provided, configured)


@method_decorator(ratelimit(key=ratelimit_ip_key, rate='20/m', method='GET', block=False), name='get')
class ActiveQuestionExportView(APIView):
    """Service-to-service export of the active question bank, correct answers included.

    Deliberately not part of the staff API surface: the caller here is another system, not a
    logged-in TA/Admin, so there is no api.User and no JWT - it authenticates with a static key
    (X-API-Key header) checked against QUESTION_EXPORT_API_KEY, in constant time so the key
    can't leak through a timing side-channel. See .env.example for how that's provisioned.

    This is intentionally the OPPOSITE of a hidden endpoint: the route is registered in
    urls.py like any other, the required setting is documented, and every successful call is
    written to AuditLog with requires_review=True so it surfaces for an admin to see - a
    service pulling the full answer key is exactly the kind of thing that should never happen
    silently, even when it's expected.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        if getattr(request, 'limited', False):
            return Response({'detail': 'Too many requests.'},
                             status=status.HTTP_429_TOO_MANY_REQUESTS)

        if not _valid_api_key(request):
            return Response({'detail': 'Invalid or missing API key.'},
                             status=status.HTTP_401_UNAUTHORIZED)

        questions = Question.objects.select_related('section').filter(
            status=Question.Status.ACTIVE,
        ).order_by('question_code')
        data = QuestionSerializer(questions, many=True).data

        log_action(
            request, user=None, action_type='service_export', entity_type='question',
            entity_id=0, details={'count': len(data)}, requires_review=True,
        )
        return Response(data)
