from django.db.models import Q

from api.models import Batch, Candidate, Question, QuestionBankSection, User
from api.serializers.batch import annotate_batch_counts
from api.services.access import visible_candidates_qs


def _batches_qs_for(user):
    qs = Batch.objects.filter(is_deleted=False)
    if user.role.role_code != 'admin':
        qs = qs.filter(Q(primary_ta_user_id=user.user_id) | Q(created_by_id=user.user_id))
    return qs


def _build_stats(batches_qs, candidates_qs):
    return {
        'active_batches': batches_qs.filter(status=Batch.Status.IN_PROGRESS).count(),
        'total_candidates': candidates_qs.count(),
        'completed': candidates_qs.filter(status=Candidate.Status.COMPLETED).count(),
        'total_pass': candidates_qs.filter(result=Candidate.Result.PASS).count(),
    }


def _build_batches_overview(batches_qs, is_admin):
    qs = annotate_batch_counts(batches_qs.select_related('primary_ta_user').order_by('-created_at'))
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
    return [
        {
            'section_name': section.section_name,
            'active_count': (active_count := section.question_set.filter(
                status=Question.Status.ACTIVE).count()),
            'min_required_active': section.min_required_active,
            'is_ok': active_count >= section.min_required_active,
        }
        for section in QuestionBankSection.objects.all()
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
