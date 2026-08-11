from api.models import AuditLog
from api.utils.net import get_client_ip


def log_action(request, user, action_type, entity_type, entity_id, details=None):
    AuditLog.objects.create(
        user=user,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        action_details=details,
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
    )
