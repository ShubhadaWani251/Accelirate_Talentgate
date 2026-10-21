"""Single seam for the app's unified Batch Status filter (Active | Completed | Draft |
Cancelled | All), shared by the batch list and the dashboard overview so "Active" means the
same set of statuses in both places rather than each screen inventing its own grouping.
"""

from api.models import Batch

STATUS_GROUPS = ('active', 'completed', 'draft', 'cancelled', 'all')


def filter_batches_by_status_group(qs, group):
    """Apply the Batch Status filter to a queryset.

    'active'    - In Progress only: batches still being worked. The default view everywhere.
    'completed' - finished batches, kept for reference.
    'draft'     - unfinished uploads only.
    'cancelled' - deactivated batches only.
    'all'       - no filtering; every status.
    Anything else, including blank/missing, defaults to 'active'.

    Completed used to be folded in with In Progress under 'active', back when nothing in the
    app could actually produce a Completed batch (see views/batches.BatchCompleteView, which
    added that). Once it could, the default view contradicted its own label and the "Active
    Batches" stat card beside it, which has always counted In Progress alone: the card read 4
    while the table under it listed 11. Completed is its own group now, so the word means the
    same thing in the count, in the table, and in the filter.
    """
    group = (group or '').strip().lower()
    if group == 'completed':
        return qs.filter(status=Batch.Status.COMPLETED)
    if group == 'draft':
        return qs.filter(status=Batch.Status.DRAFT)
    if group == 'cancelled':
        return qs.filter(status=Batch.Status.CANCELLED)
    if group == 'all':
        return qs
    return qs.filter(status=Batch.Status.IN_PROGRESS)
