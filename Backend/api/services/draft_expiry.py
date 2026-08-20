"""24-hour lifetime for Draft batches.

A Draft is an unfinished upload: rows staged from a spreadsheet, some of them still failing
validation, none of them invited, nobody committed to them yet. Left alone they accumulate
forever, so a Draft that isn't finalized within 24 hours of its creation is deleted outright -
the batch row and its staged candidates both.

The clock runs from `Batch.created_at` and nothing resets it. Editing the draft, correcting a
row, uploading more candidates and opening the wizard again all leave `created_at` untouched
(only `updated_at` is auto_now), so the deadline a batch is created with is the deadline it
keeps. The single thing that stops expiry is leaving Draft: finalizing sets IN_PROGRESS, and
this module only ever looks at status=DRAFT rows.

Three layers enforce it, deliberately overlapping:

  1. `delete_expired_draft_batches()` run by the scheduler (management command
     `delete_expired_draft_batches`) - the authoritative one, and the only layer that works
     when nobody is using the app at all.
  2. `delete_if_expired()` called from the batch-detail lookup, so touching an expired draft
     through ANY of its endpoints deletes it there and then rather than waiting for the
     scheduler. Same "lazy finalize on next touch" shape that CandidateAttemptAuthentication
     already uses for exam attempts.
  3. `exclude_expired()` applied to the list/dashboard querysets, so an expired draft stops
     being listed the moment it expires instead of at the next scheduler tick. This is
     presentation only - it hides nothing that layers 1 and 2 don't then actually delete, and
     it is NOT what makes the guarantee.

Deletion is a real row delete, not a soft `is_deleted` flag: nothing in this codebase has ever
set that flag on a Batch or Candidate, and the requirement is that the data not remain.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from api.models import Batch, Candidate

logger = logging.getLogger(__name__)

DRAFT_LIFETIME = timedelta(hours=24)


def draft_expires_at(batch):
    """When this batch stops being allowed to sit in Draft, or None if it already left Draft.

    Exactly 24 elapsed hours after creation - not "end of the next day". Both operands are
    timezone-aware (settings.USE_TZ is on, TIME_ZONE is UTC), so this is safe to compare
    against `timezone.now()` and safe to serialize straight to the browser, which renders it
    in the viewer's own zone.
    """
    if batch.status != Batch.Status.DRAFT:
        return None
    return batch.created_at + DRAFT_LIFETIME


def is_draft_expired(batch, now=None):
    deadline = draft_expires_at(batch)
    if deadline is None:
        return False
    return (now or timezone.now()) >= deadline


def expired_drafts_queryset(now=None):
    """Every Draft past its 24 hours. Server time only - `timezone.now()`, never a client clock."""
    cutoff = (now or timezone.now()) - DRAFT_LIFETIME
    return Batch.objects.filter(status=Batch.Status.DRAFT, created_at__lte=cutoff)


def exclude_expired(queryset, now=None):
    """Drop already-expired Drafts from a Batch queryset.

    Layer 3 (see module docstring): closes the window between a draft expiring and the
    scheduler getting to it, so a batch list refreshed at 24h01m doesn't show a row that is
    about to vanish. Everything not in Draft is untouched by this.
    """
    cutoff = (now or timezone.now()) - DRAFT_LIFETIME
    return queryset.exclude(status=Batch.Status.DRAFT, created_at__lte=cutoff)


def _delete_one(batch_id, now):
    """Delete one expired draft inside its own transaction, re-checking under a row lock.

    Returns the candidate count deleted, or None if the batch turned out not to be eligible
    after all (finalized or already gone between being listed and being locked).

    The re-check is the race guard: `select_for_update()` blocks until any concurrent
    BatchFinalizeView transaction on this row commits, and that view flips the status inside
    its own atomic block. So either it committed first and this sees IN_PROGRESS and backs
    off, or this deleted first and that view's own locked re-fetch raises DoesNotExist.
    """
    with transaction.atomic():
        try:
            batch = Batch.objects.select_for_update().get(batch_id=batch_id)
        except Batch.DoesNotExist:
            return None
        if batch.status != Batch.Status.DRAFT or not is_draft_expired(batch, now):
            return None

        created_at = batch.created_at
        expired_at = draft_expires_at(batch)
        candidate_count = Candidate.objects.filter(batch=batch).count()

        # One `.delete()` - the FK graph does the rest. Candidate.batch, Invitation.batch and
        # Invitation.candidate are all on_delete=CASCADE, and each Candidate takes its
        # DuplicateCheck / ExamAttempt (and that attempt's ExamAnswer + ProctoringEvent) rows
        # with it. Nothing is left pointing at a batch_id that no longer exists.
        #
        # A draft has no invites by definition, so the exam-side tables are empty in practice;
        # they cascade anyway rather than relying on that.
        batch.delete()

        # Logged with ids and counts only - never a candidate name, email or Aadhaar number.
        logger.info(
            'Deleted expired draft batch: batch_id=%s created_at=%s expired_at=%s '
            'candidates_removed=%s',
            batch_id, created_at.isoformat(), expired_at.isoformat(), candidate_count,
        )
        return candidate_count


def delete_expired_draft_batches(now=None):
    """Delete every Draft batch past its 24 hours, with its staged candidates.

    Each batch is its own transaction, so one failure rolls back only that batch and the rest
    still get processed - a single bad row can't block the sweep, and can't leave a
    half-deleted batch behind either.

    Returns {'batches_deleted', 'candidates_deleted', 'skipped', 'failed'}.
    """
    now = now or timezone.now()
    # Ids first, so the sweep isn't iterating a queryset while deleting out of it.
    batch_ids = list(expired_drafts_queryset(now).values_list('batch_id', flat=True))
    if not batch_ids:
        return {'batches_deleted': 0, 'candidates_deleted': 0, 'skipped': 0, 'failed': 0}

    logger.info('Expired draft batch cleanup started: %s candidate batch(es).', len(batch_ids))
    batches_deleted = candidates_deleted = skipped = failed = 0

    for batch_id in batch_ids:
        try:
            candidate_count = _delete_one(batch_id, now)
        except Exception:
            # Never silent: one batch failing is a real problem worth seeing, but it must not
            # stop the others. Its transaction has already rolled back, so nothing is partial.
            failed += 1
            logger.exception('Failed to delete expired draft batch_id=%s', batch_id)
            continue
        if candidate_count is None:
            skipped += 1
        else:
            batches_deleted += 1
            candidates_deleted += candidate_count

    logger.info(
        'Expired draft batch cleanup finished: batches_removed=%s candidates_removed=%s '
        'skipped=%s failed=%s', batches_deleted, candidates_deleted, skipped, failed,
    )
    return {
        'batches_deleted': batches_deleted,
        'candidates_deleted': candidates_deleted,
        'skipped': skipped,
        'failed': failed,
    }


def delete_if_expired(batch, now=None):
    """Layer 2: delete this batch if it's an expired draft. True if it was deleted.

    Called from the batch lookup every batch-scoped endpoint goes through, so an expired draft
    is removed on first contact through any of them - GET, PATCH, upload, add/remove
    candidates, finalize, send-invites - instead of being merely hidden until the scheduler
    runs. The caller then 404s.
    """
    if not is_draft_expired(batch, now):
        return False
    return _delete_one(batch.batch_id, now or timezone.now()) is not None
