from collections import Counter, defaultdict

from django.db.models import Case, Count, IntegerField, Q, Value, When

from api.models import Batch, Candidate, Question, QuestionBankSection, User
from api.serializers.batch import annotate_batch_counts
from api.serializers.question import normalize_question_text
from api.services.access import dedupe_by_profile, visible_batches_qs, visible_candidates_qs
from api.services.batch_status_filter import filter_batches_by_status_group


def _batches_qs_for(user):
    # A TA's dashboard counts and batch table cover only their own batches; an admin sees all
    # of them (services/access.visible_batches_qs). Routed through that one helper so the
    # dashboard, the batch list and can_access_batch can never drift apart.
    return visible_batches_qs(user)


def _build_stats(batches_qs, candidates_qs):
    # One aggregate query for the candidate-derived numbers (was 3 separate .count() calls),
    # same conditional-Count technique annotate_batch_counts already uses for batches.
    #
    # candidates_qs is deduped by profile (see services/access.dedupe_by_profile) before it
    # reaches here - "Total Candidates" counts real PEOPLE, matching what the All Candidates
    # page itself shows, not one count per batch appearance of the same person.
    candidate_stats = candidates_qs.aggregate(
        total_candidates=Count('candidate_id'),
        completed=Count('candidate_id', filter=Q(status=Candidate.Status.COMPLETED)),
        total_pass=Count('candidate_id', filter=Q(result=Candidate.Result.PASS)),
    )
    return {
        'active_batches': batches_qs.filter(status=Batch.Status.IN_PROGRESS).count(),
        **candidate_stats,
    }


def _build_batches_overview(batches_qs, is_admin, status_group='active'):
    # Filtered by the unified Batch Status control - 'active' (In Progress + Completed) by
    # default, so an unfinished Draft upload or a deactivated batch don't sit in the normal
    # view reporting zero candidates and zero results. Both remain fully visible by
    # switching the filter (see filter_batches_by_status_group) - nothing here is hidden
    # outright, only excluded from the default view.
    #
    # When the group mixes statuses together (status_group='all'), cancelled batches still
    # sink to the bottom rather than interleaving with active ones by date - they're not live
    # work even though they're shown.
    qs = annotate_batch_counts(
        filter_batches_by_status_group(batches_qs, status_group)
        .select_related('primary_ta_user')
        .annotate(is_cancelled=Case(
            When(status=Batch.Status.CANCELLED, then=Value(1)),
            default=Value(0), output_field=IntegerField(),
        ))
        .order_by('is_cancelled', '-created_at')
    )
    rows = []
    for batch in qs:
        row = {
            'batch_id': batch.batch_id,
            'batch_name': batch.batch_name,
            'college_name': batch.college_name,
            'total_candidates': batch.total_candidates,
            'status': batch.status,
            'status_display': batch.get_status_display(),
            'pass_count': batch.pass_count,
            'fail_count': batch.fail_count,
            'borderline_count': 0,
        }
        if is_admin:
            row['primary_ta_user_name'] = batch.primary_ta_user.full_name
        rows.append(row)
    return rows


def _build_question_bank_health():
    """Per-section readiness, counted by DISTINCT question rather than by row.

    Counting rows made this widget report OK while a section held 84 rows of only 6 distinct
    questions - an exam drawing 10 per section couldn't be built, yet the dashboard was green.
    Duplicates are now blocked at entry, but existing ones still inflate the raw count, and a
    health check that can't be trusted is worse than no health check.
    """
    active = (
        Question.objects
        .filter(status=Question.Status.ACTIVE)
        .values_list('section_id', 'question_text')
    )
    distinct_by_section = defaultdict(set)
    rows_by_section = Counter()
    for section_id, text in active:
        distinct_by_section[section_id].add(normalize_question_text(text))
        rows_by_section[section_id] += 1

    result = []
    for section in QuestionBankSection.objects.all():
        unique_count = len(distinct_by_section.get(section.section_id, ()))
        result.append({
            'section_name': section.section_name,
            'active_count': unique_count,
            'duplicate_count': rows_by_section[section.section_id] - unique_count,
            'min_required_active': section.min_required_active,
            'is_ok': unique_count >= section.min_required_active,
        })
    return result


def _build_ta_accounts():
    return [
        {
            'user_id': u.user_id,
            'full_name': u.full_name,
            'role_name': u.role.role_name,
            'is_active': u.is_active,
        }
        for u in User.objects.filter(is_deleted=False).select_related('role').order_by('first_name')
    ]


def build_dashboard_summary(user, batch_status='active'):
    """Shapes the /api/dashboard/ response: stat cards + batches overview for every caller,
    plus question-bank-health and TA-account summaries for admins only.

    `batch_status` (the dashboard's unified Batch Status filter - active/draft/cancelled/all)
    only scopes the batches_overview table, not the stat cards above it: "Active Batches",
    "Total Candidates" etc. describe the org's overall state and shouldn't change just because
    the reviewer is looking at the Draft or Cancelled list underneath.
    """
    is_admin = user.role.role_code == 'admin'
    batches_qs = _batches_qs_for(user)
    candidates_qs = dedupe_by_profile(visible_candidates_qs(user))

    response = {
        'stats': _build_stats(batches_qs, candidates_qs),
        'batches_overview': _build_batches_overview(batches_qs, is_admin, batch_status),
        'batch_status_group': (batch_status or 'active').strip().lower(),
    }
    if is_admin:
        response['question_bank_health'] = _build_question_bank_health()
        response['ta_accounts'] = _build_ta_accounts()
    return response
