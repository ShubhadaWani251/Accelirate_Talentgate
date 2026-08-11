from datetime import timedelta

from django.utils import timezone

from api.models import Candidate, DuplicateCheck


def preload_duplicate_lookup(aadhaar_numbers):
    """One query for every distinct Aadhaar number about to be checked, instead of one query
    per candidate - used by stage_candidates_from_workbook so an N-row upload does a single
    lookup query rather than N. Returns {aadhaar_number: most-recent existing Candidate}.
    """
    aadhaar_numbers = {a for a in aadhaar_numbers if a}
    if not aadhaar_numbers:
        return {}
    candidates = (
        Candidate.objects
        .filter(aadhaar_number__in=aadhaar_numbers, is_deleted=False)
        .order_by('aadhaar_number', '-created_at')
    )
    lookup = {}
    for candidate in candidates:
        lookup.setdefault(candidate.aadhaar_number, candidate)  # first seen per number = most recent
    return lookup


def run_duplicate_check(candidate, cooling_off_months=3, existing_lookup=None):
    """Match candidate's Aadhaar against historical candidates (any batch, excluding this
    one) and record a DuplicateCheck row. A prior candidate's created_at stands in for
    "last attempt date" until real ExamAttempt data exists (Phase 4) - revisit then to use
    the actual completed/terminated attempt timestamp instead.

    existing_lookup: optional {aadhaar_number: Candidate} map from preload_duplicate_lookup,
    to avoid a per-row query during bulk upload. The caller must keep it updated with each
    newly-created candidate (see stage_candidates_from_workbook) so duplicates WITHIN the same
    upload are still caught, not just duplicates against pre-existing historical candidates.
    """
    if not candidate.aadhaar_number:
        return DuplicateCheck.objects.create(
            candidate=candidate,
            check_status=DuplicateCheck.CheckStatus.NEW,
            cooling_off_months=cooling_off_months,
        )

    if existing_lookup is not None:
        existing = existing_lookup.get(candidate.aadhaar_number)
    else:
        existing = (
            Candidate.objects
            .filter(aadhaar_number=candidate.aadhaar_number, is_deleted=False)
            .exclude(candidate_id=candidate.candidate_id)
            .order_by('-created_at')
            .first()
        )
    if not existing:
        return DuplicateCheck.objects.create(
            candidate=candidate,
            check_status=DuplicateCheck.CheckStatus.NEW,
            cooling_off_months=cooling_off_months,
        )

    reference_date = existing.created_at
    cutoff = timezone.now() - timedelta(days=cooling_off_months * 30)
    status = (
        DuplicateCheck.CheckStatus.DUPLICATE_WITHIN_WINDOW
        if reference_date > cutoff
        else DuplicateCheck.CheckStatus.DUPLICATE_CLEARED
    )
    return DuplicateCheck.objects.create(
        candidate=candidate,
        check_status=status,
        existing_candidate=existing,
        existing_attempt_date=reference_date,
        cooling_off_months=cooling_off_months,
    )


def clear_duplicate(candidate, user):
    """Manually clear a DUPLICATE_WITHIN_WINDOW flag at staff discretion."""
    check = candidate.duplicate_checks.order_by('-checked_at').first()
    if not check:
        return None
    check.check_status = DuplicateCheck.CheckStatus.DUPLICATE_CLEARED
    check.checked_by = user
    check.checked_at = timezone.now()
    check.save(update_fields=['check_status', 'checked_by', 'checked_at'])
    return check
