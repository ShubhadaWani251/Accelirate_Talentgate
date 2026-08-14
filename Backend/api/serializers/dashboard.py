from django.db.models import Case, Count, IntegerField, Q, Value, When

from api.models import Batch, Candidate, Question, QuestionBankSection, User
from api.serializers.batch import annotate_batch_counts
from api.services.access import visible_candidates_qs


def _batches_qs_for(user):
    # Every TA sees every batch, same as an admin - the owner narrowing that used to live here
    # was removed deliberately (see services/access.py for the rationale). Kept as a function
    # so the dashboard has the same single seam the other call sites do.
    return Batch.objects.filter(is_deleted=False)


def _build_stats(batches_qs, candidates_qs):
    # One aggregate query for the candidate-derived numbers (was 3 separate .count() calls),
    # same conditional-Count technique annotate_batch_counts already uses for batches.
    candidate_stats = candidates_qs.aggregate(
        total_candidates=Count('candidate_id'),
        completed=Count('candidate_id', filter=Q(status=Candidate.Status.COMPLETED)),
        total_pass=Count('candidate_id', filter=Q(result=Candidate.Result.PASS)),
    )
    return {
        'active_batches': batches_qs.filter(status=Batch.Status.IN_PROGRESS).count(),
        **candidate_stats,
    }


def _build_batches_overview(batches_qs, is_admin):
    # Deactivated batches sink to the bottom rather than being hidden - they still hold real
    # candidates and results a TA may need to look up, but they're not live work, so they
    # shouldn't push active batches down the list.
    qs = annotate_batch_counts(
        batches_qs.select_related('primary_ta_user')
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
    sections = QuestionBankSection.objects.annotate(
        active_count=Count('question', filter=Q(question__status=Question.Status.ACTIVE))
    )
    return [
        {
            'section_name': section.section_name,
            'active_count': section.active_count,
            'min_required_active': section.min_required_active,
            'is_ok': section.active_count >= section.min_required_active,
        }
        for section in sections
    ]


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


def build_dashboard_summary(user):
    """Shapes the /api/dashboard/ response: stat cards + batches overview for every caller,
    plus question-bank-health and TA-account summaries for admins only.
    """
    is_admin = user.role.role_code == 'admin'
    batches_qs = _batches_qs_for(user)
    candidates_qs = visible_candidates_qs(user)

    response = {
        'stats': _build_stats(batches_qs, candidates_qs),
        'batches_overview': _build_batches_overview(batches_qs, is_admin),
    }
    if is_admin:
        response['question_bank_health'] = _build_question_bank_health()
        response['ta_accounts'] = _build_ta_accounts()
    return response
