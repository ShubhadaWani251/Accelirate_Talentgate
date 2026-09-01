"""Manual deletion of Draft batches.

A Draft is an unfinished upload: rows staged from a spreadsheet, some of them still failing
validation, none of them invited, nobody committed to them yet. There used to be an automatic
24-hour expiry that deleted an unfinished Draft on its own - that was removed (drafts now sit
indefinitely until someone deals with them) in favor of a plain, explicit "Delete" action a
TA/admin takes from the Drafts list. See BatchDetailView.delete and BatchList.jsx.

Deletion is a real row delete, not a soft `is_deleted` flag: nothing in this codebase has ever
set that flag on a Batch or Candidate, and the requirement is that the data not remain.
"""

import logging

from django.db import transaction

from api.models import Batch, Candidate

logger = logging.getLogger(__name__)


def delete_draft_batch(batch):
    """Delete one Draft batch right now, on a TA/admin's explicit request.

    Returns {'batch_name', 'candidates_removed'}. Raises ValueError if the batch is not
    currently a Draft - re-checked under the row lock, so a batch finalized by someone else in
    the instant between the caller reading its status and this running can't be deleted out
    from under that finalize.
    """
    with transaction.atomic():
        locked = Batch.objects.select_for_update().get(pk=batch.pk)
        if locked.status != Batch.Status.DRAFT:
            raise ValueError('Only a Draft batch can be deleted this way.')

        candidate_count = Candidate.objects.filter(batch=locked).count()
        batch_name = locked.batch_name
        # One `.delete()` - the FK graph does the rest. Candidate.batch, Invitation.batch and
        # Invitation.candidate are all on_delete=CASCADE, and each Candidate takes its
        # DuplicateCheck / ExamAttempt (and that attempt's ExamAnswer + ProctoringEvent) rows
        # with it. A draft has no invites by definition, so the exam-side tables are empty in
        # practice; they cascade anyway rather than relying on that.
        locked.delete()

        # Logged with ids and counts only - never a candidate name, email or Aadhaar number.
        logger.info(
            'Deleted draft batch by request: batch_id=%s candidates_removed=%s',
            batch.batch_id, candidate_count,
        )
        return {'batch_name': batch_name, 'candidates_removed': candidate_count}
