from django.db.models import Q

from api.models import Candidate


def can_access_batch(user, batch):
    """Shared visibility rule for batch-scoped resources (batches, candidates, dashboard stats).

    Admins see everything; a Staffing User (TA) sees only batches they own as the primary TA or
    that they personally created - kept in one place since batches.py, candidates.py, and
    dashboard.py all need the identical rule and previously drifted into a private cross-module
    import instead.
    """
    return user.role.role_code == 'admin' or batch.primary_ta_user_id == user.user_id \
        or batch.created_by_id == user.user_id


def visible_candidates_qs(user):
    """Candidate queryset scoped by the same rule as can_access_batch, expressed as a filter
    so callers (candidate list/export/notify, dashboard stats) don't each re-derive it.
    """
    qs = Candidate.objects.select_related('batch').filter(is_deleted=False, batch__is_deleted=False)
    if user.role.role_code != 'admin':
        qs = qs.filter(Q(batch__primary_ta_user_id=user.user_id) | Q(batch__created_by_id=user.user_id))
    return qs
