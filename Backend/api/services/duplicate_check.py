from datetime import timedelta

from django.utils import timezone

from api.models import Candidate, DuplicateCheck, ExamAttempt
from api.services.candidate_validation import candidate_identity_key


def preload_duplicate_lookup(aadhaar_last4_values):
    """One query for every distinct Aadhaar suffix about to be checked, instead of one query
    per candidate - used by stage_candidates_from_workbook so an N-row upload does a single
    lookup query rather than N.

    Returns {(last4, dob_iso): [Candidate, ...]} newest first. The SQL filter is on the 4
    digits alone (that is the indexed column), and the DOB half of the key is applied in Python
    when building the map - so the query stays index-backed while the key stays specific enough
    to be meaningful. See candidate_validation.identity_key for why DOB is part of it.

    Every prior record is kept, not just the newest: the deciding fact is whether the person
    ever SAT the assessment, and that attempt may belong to an older record than the most
    recent upload of the same person.
    """
    aadhaar_last4_values = {a for a in aadhaar_last4_values if a}
    if not aadhaar_last4_values:
        return {}
    lookup = {}
    for candidate in (Candidate.objects
                      .filter(aadhaar_last4__in=aadhaar_last4_values, is_deleted=False)
                      .order_by('aadhaar_last4', '-created_at')):
        lookup.setdefault(candidate_identity_key(candidate), []).append(candidate)
    return lookup


def _latest_attempt_across(candidates):
    """(candidate, attempt_date) for the most recent completed attempt among `candidates`,
    or (None, None) if none of them ever sat the assessment.

    Only a finished attempt counts - an abandoned in-progress row shouldn't start a
    cooling-off period. One query for the whole set rather than one per candidate.
    """
    by_id = {c.candidate_id: c for c in candidates}
    if not by_id:
        return None, None

    best_candidate, best_date = None, None
    attempts = ExamAttempt.objects.filter(
        candidate_id__in=by_id,
        status__in=(ExamAttempt.Status.SUBMITTED, ExamAttempt.Status.TERMINATED),
    ).only('candidate_id', 'started_at', 'submitted_at', 'terminated_at')
    for attempt in attempts:
        when = attempt.submitted_at or attempt.terminated_at or attempt.started_at
        if when and (best_date is None or when > best_date):
            best_candidate, best_date = by_id[attempt.candidate_id], when
    return best_candidate, best_date


def run_duplicate_check(candidate, cooling_off_months=3, existing_lookup=None):
    """Match candidate against historical candidates (any batch, excluding this one) and
    record a DuplicateCheck row.

    Matching is on (Aadhaar last 4 + date of birth), not the digits alone - see
    candidate_validation.identity_key. Only 4 digits are stored now, and matching on those
    alone would flag roughly one unrelated pair in every 50-row batch as a duplicate.

    The cooling-off window is measured from when the earlier record actually SAT the
    assessment, not from when it was uploaded. Using the upload date meant a candidate who
    merely appeared in an untouched draft batch - or was invited and never showed up - came
    back flagged as a red "Duplicate Within Window" and blocked, despite never having taken
    a test. Those cases are now PREVIOUSLY_INVITED: worth surfacing, not worth blocking.

    existing_lookup: optional {identity_key: [Candidate]} map from preload_duplicate_lookup,
    to avoid a per-row query during bulk upload. The caller must keep it updated with each
    newly-created candidate (see stage_candidates_from_workbook) so duplicates WITHIN the same
    upload are still caught, not just duplicates against pre-existing historical candidates.
    """
    if not candidate.aadhaar_last4 or not candidate.date_of_birth:
        return DuplicateCheck.objects.create(
            candidate=candidate,
            check_status=DuplicateCheck.CheckStatus.NEW,
            cooling_off_months=cooling_off_months,
        )

    key = candidate_identity_key(candidate)
    if existing_lookup is not None:
        matches = list(existing_lookup.get(key) or [])
    else:
        # Filtered on the indexed 4 digits in SQL, then narrowed to the full identity key in
        # Python - matching the exact tuple identity_key() builds, rather than re-deriving an
        # equivalent SQL comparison that could drift out of sync with it.
        matches = [
            m for m in Candidate.objects
            .filter(aadhaar_last4=candidate.aadhaar_last4, is_deleted=False)
            .order_by('-created_at')
            if candidate_identity_key(m) == key
        ]
    matches = [m for m in matches if m.candidate_id != candidate.candidate_id]
    if not matches:
        return DuplicateCheck.objects.create(
            candidate=candidate,
            check_status=DuplicateCheck.CheckStatus.NEW,
            cooling_off_months=cooling_off_months,
        )

    attempted, attempt_date = _latest_attempt_across(matches)
    if attempt_date is None:
        # Every prior record exists but none ever sat the assessment - untouched draft batches,
        # or invites that went unanswered. Nothing to cool off from, so surface the most recent
        # record for context and move on.
        return DuplicateCheck.objects.create(
            candidate=candidate,
            check_status=DuplicateCheck.CheckStatus.PREVIOUSLY_INVITED,
            existing_candidate=matches[0],
            cooling_off_months=cooling_off_months,
        )
    existing = attempted

    cutoff = timezone.now() - timedelta(days=cooling_off_months * 30)
    status = (
        DuplicateCheck.CheckStatus.DUPLICATE_WITHIN_WINDOW
        if attempt_date > cutoff
        else DuplicateCheck.CheckStatus.DUPLICATE_CLEARED
    )
    return DuplicateCheck.objects.create(
        candidate=candidate,
        check_status=status,
        existing_candidate=existing,
        existing_attempt_date=attempt_date,
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
