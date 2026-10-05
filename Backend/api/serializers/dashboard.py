from collections import defaultdict
from datetime import timedelta

from django.db.models import Case, Count, IntegerField, OuterRef, Q, Subquery, Value, When
from django.utils import timezone

from api.models import Batch, Candidate, ExamAttempt, Question, QuestionBankSection, User
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
    #
    # "Completed" can't filter on Candidate.status=COMPLETED - nothing ever writes that value.
    # The exam-taking flow only ever moves Candidate.status pending_invite -> invited (see
    # serializers/candidates._effective_status's own comment); a candidate's real progress lives
    # on their latest ExamAttempt instead, exactly like the Status column on every candidate
    # list/detail view already computes it. This card was reporting 0 for exactly that reason,
    # regardless of how many candidates had actually finished. Ordered by -attempt_id, not
    # -started_at, for the same reason _latest_attempt is (see serializers/candidates.py).
    latest_attempt_status = Subquery(
        ExamAttempt.objects.filter(candidate=OuterRef('pk'))
        .order_by('-attempt_id').values('status')[:1]
    )
    # When that same latest attempt finished, which is the only timestamp tied to a candidate's
    # progress - Candidate.result itself records no date, so "when did this become a pass" can
    # only be answered by when the attempt it came from was submitted.
    latest_submitted_at = Subquery(
        ExamAttempt.objects.filter(candidate=OuterRef('pk'))
        .order_by('-attempt_id').values('submitted_at')[:1]
    )
    # Each *_this_week figure counts what ARRIVED in the last seven days, which for a running
    # total is exactly how much higher the number is than it was a week ago. No previous-period
    # snapshot is stored anywhere, so this is derived from timestamps rather than compared
    # against history - see the frontend, which labels these "+N this week" rather than implying
    # a stored comparison it cannot make.
    #
    # active_batches is the one approximation: a batch can stop being active without leaving a
    # trace of when, so its figure counts batches CREATED active in the window. The other three
    # are exact, because a candidate, a submission and a result only ever accumulate.
    #
    # Folded into the two aggregates that already run rather than added as fresh queries: this
    # costs the dashboard no extra round trips.
    week_ago = timezone.now() - timedelta(days=7)
    candidate_stats = candidates_qs.annotate(
        latest_attempt_status=latest_attempt_status,
        latest_submitted_at=latest_submitted_at,
    ).aggregate(
        total_candidates=Count('candidate_id'),
        completed=Count('candidate_id', filter=Q(latest_attempt_status=ExamAttempt.Status.SUBMITTED)),
        total_pass=Count('candidate_id', filter=Q(result=Candidate.Result.PASS)),
        total_candidates_this_week=Count('candidate_id', filter=Q(created_at__gte=week_ago)),
        completed_this_week=Count('candidate_id', filter=Q(
            latest_attempt_status=ExamAttempt.Status.SUBMITTED,
            latest_submitted_at__gte=week_ago)),
        total_pass_this_week=Count('candidate_id', filter=Q(
            result=Candidate.Result.PASS, latest_submitted_at__gte=week_ago)),
    )
    batch_stats = batches_qs.aggregate(
        active_batches=Count('batch_id', filter=Q(status=Batch.Status.IN_PROGRESS)),
        active_batches_this_week=Count('batch_id', filter=Q(
            status=Batch.Status.IN_PROGRESS, created_at__gte=week_ago)),
    )
    return {**batch_stats, **candidate_stats}


def _build_batches_overview(batches_qs, is_admin, status_group='active'):
    # Filtered by the unified Batch Status control - 'active' (In Progress + Completed) by
    # default, so an unfinished Draft upload or a deactivated batch don't sit in the normal
    # view reporting zero candidates and zero results. Both remain fully visible by
    # switching the filter (see filter_batches_by_status_group) - nothing here is hidden
    # outright, only excluded from the default view.
    #
    # Ordered by how much attention a batch still wants, then newest-first within each band.
    # Sorting by date alone interleaved finished batches with live ones, so the rows a TA can
    # still act on were scattered down a list they had to read all of - and the default Active
    # view holds both In Progress and Completed, which is where it showed most.
    #
    #   0  in progress (and drafts, in the groups that include them) - live work
    #   1  completed   - done, kept for reference
    #   2  cancelled   - not work at all, even though it is shown
    qs = annotate_batch_counts(
        filter_batches_by_status_group(batches_qs, status_group)
        .select_related('primary_ta_user')
        .annotate(status_rank=Case(
            When(status=Batch.Status.COMPLETED, then=Value(1)),
            When(status=Batch.Status.CANCELLED, then=Value(2)),
            default=Value(0), output_field=IntegerField(),
        ))
        .order_by('status_rank', '-created_at')
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
            'borderline_count': batch.borderline_count,
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
    for section_id, text in active:
        distinct_by_section[section_id].add(normalize_question_text(text))

    result = []
    # Active only, same reasoning as the question template (services/question_bank.py): this
    # panel exists to tell an admin which sections still need questions before a batch can run
    # them. A retired section cannot be run at all, so reporting it as short of its minimum is
    # an alarm about work that would be wasted.
    for section in QuestionBankSection.objects.filter(is_active=True):
        unique_count = len(distinct_by_section.get(section.section_id, ()))
        result.append({
            'section_name': section.section_name,
            'active_count': unique_count,
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
