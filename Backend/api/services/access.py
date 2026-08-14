from api.models import Candidate


# Batch data is shared across the whole Talent Acquisition team: any Staffing User can see and
# work every batch, not just the ones they own. Ownership (Batch.primary_ta_user) still records
# who runs a batch and is shown in the UI - it just no longer restricts who can see it, so a TA
# can cover a colleague's drive without needing the batch reassigned first.
#
# These two helpers are kept as the single seam for that rule. Re-scoping to per-owner
# visibility later means changing them here and nowhere else - callers in batches.py,
# candidates.py and dashboard.py all route through them.
#
# Note both endpoints groups are still gated to authenticated admin/TA users by IsAdminOrTA;
# this only removes the *within-role* narrowing. Admin-only areas (Question Bank, User
# Management) are unaffected - those are gated separately by IsAdmin.


def can_access_batch(user, batch):
    """Shared visibility rule for batch-scoped resources (batches, candidates, dashboard stats).

    Admins and Staffing Users both see every batch - see the module note above.
    """
    return user.role.role_code in ('admin', 'ta')


def visible_candidates_qs(user):
    """Candidate queryset scoped by the same rule as can_access_batch, expressed as a filter
    so callers (candidate list/export/notify, dashboard stats) don't each re-derive it.
    """
    return Candidate.objects.select_related('batch').filter(
        is_deleted=False, batch__is_deleted=False,
    )
