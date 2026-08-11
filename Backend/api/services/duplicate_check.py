from datetime import timedelta

from django.utils import timezone

from api.models import Candidate, DuplicateCheck


def run_duplicate_check(candidate, cooling_off_months=3):
    """Match candidate's Aadhaar against historical candidates (any batch, excluding this
    one) and record a DuplicateCheck row. A prior candidate's created_at stands in for
    "last attempt date" until real ExamAttempt data exists (Phase 4) - revisit then to use
    the actual completed/terminated attempt timestamp instead.
    """
    if not candidate.aadhaar_number:
        return DuplicateCheck.objects.create(
            candidate=candidate,
            check_status=DuplicateCheck.CheckStatus.NEW,
            cooling_off_months=cooling_off_months,
        )

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
