from django.db.models import Q

from api.models import Batch, Candidate


# Batch visibility is scoped by creator: a Staffing User sees only the batches they created.
# Administrators see every batch, since they oversee the whole pipeline.
#
# This was previously shared across the whole TA team, deliberately, so a TA could cover a
# colleague's drive. That was reversed on request - each TA now gets their own view. The
# trade-off is real and worth knowing: if a TA leaves or is away, their batches are visible
# only to an administrator until the batch is reassigned.
#
# Scoped on `created_by` rather than `primary_ta_user` because "created by them" is the rule
# asked for. The two are set to the same user at creation (see BatchListCreateView.post), so
# today they are interchangeable; they would diverge only if a batch were ever reassigned to a
# different primary owner, and in that case the creator - not the new owner - keeps the view.
#
# These helpers are the single seam for the rule. Callers in batches.py, candidates.py and
# dashboard.py all route through them, so changing visibility again means changing it here and
# nowhere else.
#
# Note both endpoint groups are still gated to authenticated admin/TA users by IsAdminOrTA;
# this is the *within-role* narrowing. Admin-only areas (Question Bank, User Management) are
# unaffected - those are gated separately by IsAdmin.


def is_admin(user):
    return user.role.role_code == 'admin'


def can_access_batch(user, batch):
    """Shared visibility rule for batch-scoped resources (batches, candidates, dashboard stats).

    Admins see every batch; a Staffing User sees only batches they created.
    """
    if is_admin(user):
        return True
    if user.role.role_code != 'ta':
        return False
    return batch.created_by_id == user.user_id


def visible_batches_qs(user):
    """Batch queryset scoped by the same rule as can_access_batch.

    Expressed as a filter so the list, dashboard and any future batch-scoped screen narrow
    identically rather than each re-deriving it - the bug this prevents is a batch that 404s on
    its detail page while still being counted in a list.
    """
    qs = Batch.objects.filter(is_deleted=False)
    if is_admin(user):
        return qs
    return qs.filter(created_by=user)


def visible_candidates_qs(user):
    """Candidate queryset scoped by the same rule as can_access_batch, expressed as a filter
    so callers (candidate list/export/notify, dashboard stats) don't each re-derive it.

    Candidates on a DRAFT batch are excluded. Those rows are staging data for an upload that
    hasn't been completed - they may still be failing validation, and nobody has decided yet
    which of them are even going to be invited. They belong to the upload wizard's review
    table (which reads them directly off the batch) and nowhere else, so they don't turn up
    in All Candidates, exports, notifications or the dashboard counts.

    NOT scoped by uploader. All Candidates deliberately shows every candidate in the system
    regardless of who uploaded them, for admins and Staffing Users alike - a TA covering a
    colleague's drive, or picking up a handover, has to be able to find the person.

    This is intentionally asymmetric with visible_batches_qs above, which IS per-creator, and
    the asymmetry is the point rather than an oversight: the candidate LIST is a directory of
    people, while the batch list is a work queue. The visible consequence is that a TA can open
    a candidate belonging to someone else's batch and see their record, but following the Batch
    Name column through to that batch's own page still 404s. Both halves were asked for
    explicitly; if the batch page should open too, visible_batches_qs is the one line to change.
    """
    return Candidate.objects.select_related('batch').filter(
        is_deleted=False, batch__is_deleted=False,
    ).exclude(batch__status=Batch.Status.DRAFT)


def dedupe_by_profile(qs):
    """Collapse `qs` to one row per real person: the most recently created CandidateProfile
    membership, plus every row with no profile (no Aadhaar+DOB to key on, so nothing to dedupe
    against - see services/candidate_profile.py). This is the shared "how many PEOPLE, not
    batch-appearances" rule - the All Candidates listing (views/candidates.CandidateListView,
    when not scoped to one batch) and the dashboard's stat cards both need exactly this, and
    used to compute it independently, which is exactly how they could silently disagree.

    Reduced in Python rather than a DISTINCT ON query: this needs to run on both Postgres
    (production) and SQLite (settings_test.py deliberately uses SQLite - see its module
    docstring), and DISTINCT ON is Postgres-only.
    """
    latest_membership_ids = []
    seen_profiles = set()
    for candidate_id, profile_id in (
        qs.filter(profile__isnull=False)
        .order_by('profile_id', '-created_at')
        .values_list('candidate_id', 'profile_id')
    ):
        if profile_id not in seen_profiles:
            seen_profiles.add(profile_id)
            latest_membership_ids.append(candidate_id)
    return qs.filter(Q(candidate_id__in=latest_membership_ids) | Q(profile__isnull=True))
