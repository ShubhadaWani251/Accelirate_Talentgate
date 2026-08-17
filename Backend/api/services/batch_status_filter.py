"""Single seam for the app's unified Batch Status filter (Active | Draft | Cancelled | All),
shared by the batch list and the dashboard overview so "Active" means the same set of
statuses in both places rather than each screen inventing its own grouping.
"""

from api.models import Batch

STATUS_GROUPS = ('active', 'draft', 'cancelled', 'all')


def filter_batches_by_status_group(qs, group):
    """Apply the Batch Status filter to a queryset.

    'active'    - everything except Draft and Cancelled (In Progress + Completed) - the
                  normal, currently-working batches, and the default view everywhere.
    'draft'     - unfinished uploads only.
    'cancelled' - deactivated batches only.
    'all'       - no filtering; every status.
    Anything else, including blank/missing, defaults to 'active'.
    """
    group = (group or '').strip().lower()
    if group == 'draft':
        return qs.filter(status=Batch.Status.DRAFT)
    if group == 'cancelled':
        return qs.filter(status=Batch.Status.CANCELLED)
    if group == 'all':
        return qs
    return qs.exclude(status__in=(Batch.Status.DRAFT, Batch.Status.CANCELLED))
