"""DRF exception handler that guarantees a JSON body for every error response.

DRF's own handler only understands APIException, Http404 and PermissionDenied. Anything else -
an IntegrityError, a KeyError in a serializer, a provider client blowing up - is re-raised and
handled by Django, which renders an HTML error page. Every consumer of this API is an axios
client that reads `res.data.detail` (see Frontend/src/api/axiosClient.js), so an HTML body
surfaces in the UI as an unreadable error and the actual cause is lost.
"""

import logging

from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


def api_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is not None:
        return response

    # Not something DRF recognises, so this is an unhandled server-side fault.
    #
    # Deliberately generic to the client: the exception's own message can carry connection
    # strings, SQL fragments with candidate PII, or provider responses that echo an API key
    # (the same reasoning as services/invites.summarize_send_error). The detail lives in the
    # log, which is where whoever is fixing it will be looking.
    #
    # Http404 and PermissionDenied are listed for clarity even though DRF already converts
    # them - if a future DRF release stops doing that, they must not become 500s.
    if isinstance(exc, Http404):
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, PermissionDenied):
        return Response({'detail': 'You do not have permission to perform this action.'},
                        status=status.HTTP_403_FORBIDDEN)

    view = context.get('view')
    request = context.get('request')
    logger.exception(
        'Unhandled exception in %s (%s %s)',
        view.__class__.__name__ if view else 'unknown view',
        getattr(request, 'method', '?'),
        getattr(request, 'path', '?'),
    )
    return Response(
        {'detail': 'An unexpected server error occurred. Please try again, and contact your '
                   'administrator if it keeps happening.'},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
