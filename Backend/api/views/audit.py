"""Audit Log screen - a read-only view of who did what, across the whole application.

Admin-only: it exposes every user's activity, which is precisely what makes it useful for
oversight and precisely why a Staffing User shouldn't see it.

Read-only by design. AuditLog is an append-only record; there is no update or delete endpoint
here, and there shouldn't be - a log an administrator can edit is not evidence of anything.
"""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import AuditLog, User
from api.pagination import StandardResultsPagination
from api.permissions import IsAdmin
from api.serializers.audit import AuditLogSerializer


class AuditLogListView(APIView):
    """GET /api/audit-logs/ - newest first, paginated, with filters.

    Filters (all optional, combined with AND):
      user      - user_id
      action    - action_type, exact
      entity    - entity_type, exact
      search    - substring across the acting user's name/email and the raw codes
      date_from - ISO date (inclusive), server timezone
      date_to   - ISO date (inclusive - the whole day, not midnight)
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = AuditLog.objects.select_related('user', 'user__role')

        user_id = request.query_params.get('user', '').strip()
        if user_id.isdigit():
            qs = qs.filter(user_id=int(user_id))

        action = request.query_params.get('action', '').strip()
        if action:
            qs = qs.filter(action_type=action)

        entity = request.query_params.get('entity', '').strip()
        if entity:
            qs = qs.filter(entity_type=entity)

        date_from = _parse_date(request.query_params.get('date_from'))
        if date_from:
            qs = qs.filter(created_at__gte=date_from)

        date_to = _parse_date(request.query_params.get('date_to'))
        if date_to:
            # Inclusive of the whole end day: a filter of 20-Aug..20-Aug should return that
            # day's rows, not nothing because everything happened after 00:00.
            qs = qs.filter(created_at__lt=date_to + timedelta(days=1))

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(user__email__icontains=search)
                | Q(action_type__icontains=search)
                | Q(entity_type__icontains=search)
            )

        # Model Meta already orders by -created_at; restated so a change there can't silently
        # flip this screen into oldest-first.
        qs = qs.order_by('-created_at', '-log_id')

        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        response = paginator.get_paginated_response(AuditLogSerializer(page, many=True).data)
        return response


class AuditLogFilterOptionsView(APIView):
    """GET /api/audit-logs/filters/ - the values the filter dropdowns should offer.

    Built from what is actually in the table rather than from a hardcoded list, so a newly
    added action type becomes filterable without a frontend change, and an action type nobody
    has ever performed doesn't clutter the dropdown.
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        actions = (AuditLog.objects.order_by('action_type')
                   .values_list('action_type', flat=True).distinct())
        entities = (AuditLog.objects.order_by('entity_type')
                    .values_list('entity_type', flat=True).distinct())
        users = (User.objects.filter(is_deleted=False)
                 .order_by('first_name', 'last_name')
                 .values('user_id', 'first_name', 'last_name', 'email'))
        return Response({
            'actions': [
                {'value': a, 'label': (a or '').replace('_', ' ').capitalize()}
                for a in actions if a
            ],
            'entities': [
                {'value': e, 'label': (e or '').replace('_', ' ').capitalize()}
                for e in entities if e
            ],
            'users': [
                {
                    'value': u['user_id'],
                    'label': ' '.join(
                        p for p in (u['first_name'], u['last_name']) if p
                    ) or u['email'],
                }
                for u in users
            ],
        })


def _parse_date(raw):
    """Parse an ISO date into an aware datetime at the start of that day, or None.

    Returns None for anything unparseable rather than raising: a malformed date in a query
    string should narrow nothing, not 400 the whole screen.
    """
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        parsed = timezone.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed
