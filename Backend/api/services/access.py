from django.db.models import Q

from api.models import Batch, Candidate


# Every batch is visible to every member of staff. A Staffing User sees - and can manage -
# the same batches an administrator does.
#
# This has been both ways before. It was team-wide, then narrowed to each TA's own batches on
# request, and is now team-wide again because that narrowing had a cost nobody wanted: a TA who
# was away or had left took their drives with them, and covering for a colleague needed an
# administrator. Sharing is what a recruitment desk actually does.
#
# What this does NOT do is make a Staffing User an administrator. The difference is no longer
# about WHICH batches, it is about which controls:
#
#   section cutoffs     admin-only (views/batches.BatchDetailView.patch, BatchCutoffPreviewView)
#                       - they decide who passed, so revising one silently re-grades results
#   default batch config  admin-only (BatchDefaultsView) - org-wide, every FUTURE batch
#   question bank, user management, audit log   admin-only, gated by IsAdmin
#
# Those gates are on the role, not on ownership, so they are unaffected by anything here.
# Everything else a batch can do - edit, upload, finalize, send invites, deactivate, complete -
# a Staffing User may now do on any batch, not just their own. The audit log records the actor
# on every one of them, which is what keeps a shared desk accountable.
#
# These helpers remain the single seam for the rule. Callers in batches.py, candidates.py and
# dashboard.py all route through them, so changing visibility again means changing it here and
# nowhere else.
#
# One consequence worth knowing: the TA dashboard's batch counts are now org-wide rather than
# personal. Its candidate counts always were (see visible_candidates_qs), so this removes an
# inconsistency rather than creating one - the two halves of that screen now count the same
# population.


def is_admin(user):
    return user.role.role_code == 'admin'


def can_access_batch(user, batch):
    """Shared visibility rule for batch-scoped resources (batches, candidates, dashboard stats).

    Admins and Staffing Users alike reach every batch. `batch` is still taken, and the role is
    still checked, because neither is dead weight: the role check is what keeps a principal
    that is not staff at all out, and the parameter is what lets this become per-batch again -
    a reassignment rule, an archive flag - without touching a single caller.

    Read through getattr for the same reason permissions.py does: a candidate's ExamAttempt
    authenticates through a different class (authentication.CandidateAttemptAuthentication) and
    has no `role` at all, so a bare attribute read would raise here rather than refuse.
    """
    role = getattr(user, 'role', None)
    return getattr(role, 'role_code', None) in ('admin', 'ta')


def visible_batches_qs(user):
    """Batch queryset scoped by the same rule as can_access_batch: every live batch, for staff.

    Still takes `user`, and every caller still passes it, although nothing reads it today. That
    is the point of a seam - the day this narrows again (by team, by region, by an archive
    flag) it narrows here, and the list, the dashboard and every batch-scoped screen follow
    without being found and edited one at a time. Dropping the parameter now would mean
    putting it back into every call site then.

    The bug the shared helper prevents, which outlived the per-creator rule: a batch that 404s
    on its detail page while still being counted in a list.
    """
    return Batch.objects.filter(is_deleted=False)


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
