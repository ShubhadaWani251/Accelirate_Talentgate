"""Django admin registrations - DEBUG-only convenience dashboard for local testing.

This module is only ever imported when settings.DEBUG is True (see INSTALLED_APPS in
config/settings.py and the admin route in config/urls.py) - it never exists in a real
deployment. That gate is what makes this safe to register broadly: the original removal of
django.contrib.admin (see the comment in settings.py) was about it being reachable in production
as a full RBAC bypass, not about local developers being unable to see their own dev database.

Two things stay off-limits even here, because "local only" doesn't make them harmless to form a
habit around:
  - AuditLog is registered read-only. It's an append-only log everywhere else in this app: the
    admin shouldn't be the one place that quietly isn't.
  - Any stored hash (User.password_hash, PasswordHistoryEntry.password_hash) is excluded from
    every form. There is no legitimate reason to ever look at one, testing included.
"""
from django.contrib import admin

from api.models import (
    AuditLog,
    Batch,
    Candidate,
    DuplicateCheck,
    ExamAnswer,
    ExamAttempt,
    Invitation,
    OTPVerification,
    PasswordHistoryEntry,
    Permission,
    ProctoringEvent,
    Question,
    QuestionBankSection,
    RevokedRefreshToken,
    Role,
    RolePermission,
    Setting,
    User,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Browsable, never mutable - see the AuditLog note above."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    list_display = ('log_id', 'created_at', 'action_type', 'entity_type', 'entity_id', 'user',
                     'requires_review')
    list_filter = ('action_type', 'entity_type', 'requires_review')
    search_fields = ('entity_type', 'action_type', 'user__email')
    date_hierarchy = 'created_at'


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    exclude = ('password_hash',)
    list_display = ('user_id', 'email', 'first_name', 'last_name', 'role', 'is_active',
                     'is_deleted', 'created_at')
    list_filter = ('role', 'is_active', 'is_deleted')
    search_fields = ('email', 'first_name', 'last_name')


@admin.register(PasswordHistoryEntry)
class PasswordHistoryEntryAdmin(ReadOnlyAdmin):
    exclude = ('password_hash',)
    list_display = ('history_id', 'user', 'created_at')
    search_fields = ('user__email',)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('question_code', 'section', 'difficulty', 'status', 'marks', 'created_at')
    list_filter = ('section', 'difficulty', 'status')
    search_fields = ('question_code', 'question_text')


@admin.register(QuestionBankSection)
class QuestionBankSectionAdmin(admin.ModelAdmin):
    list_display = ('section_name', 'section_key', 'min_required_active')


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ('batch_id', 'batch_name', 'status', 'primary_ta_user', 'total_candidates',
                     'created_at', 'is_deleted')
    list_filter = ('status', 'is_deleted')
    search_fields = ('batch_name',)


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ('candidate_id', 'full_name', 'email', 'batch', 'status', 'result',
                     'is_deleted')
    list_filter = ('status', 'result', 'is_deleted')
    search_fields = ('email', 'first_name', 'last_name')


@admin.register(DuplicateCheck)
class DuplicateCheckAdmin(admin.ModelAdmin):
    list_display = ('check_id', 'candidate', 'check_status', 'existing_candidate')
    list_filter = ('check_status',)


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ('invitation_id', 'candidate', 'batch', 'email_status', 'retry_count',
                     'is_link_used', 'link_expired_at')
    list_filter = ('email_status', 'is_link_used')


@admin.register(ExamAttempt)
class ExamAttemptAdmin(admin.ModelAdmin):
    list_display = ('attempt_id', 'candidate', 'invitation', 'status', 'overall_score',
                     'id_verified_at')
    list_filter = ('status',)


@admin.register(ExamAnswer)
class ExamAnswerAdmin(admin.ModelAdmin):
    list_display = ('answer_id', 'attempt', 'question', 'selected_option', 'is_correct')
    list_filter = ('is_correct',)


@admin.register(ProctoringEvent)
class ProctoringEventAdmin(ReadOnlyAdmin):
    list_display = ('event_id', 'attempt', 'event_type', 'is_violation', 'severity',
                     'event_timestamp')
    list_filter = ('event_type', 'is_violation', 'severity')


admin.site.register(Role)
admin.site.register(Permission)
admin.site.register(RolePermission)
admin.site.register(OTPVerification)
admin.site.register(RevokedRefreshToken)
admin.site.register(Setting)

admin.site.site_header = 'TalentGate (local dev only)'
admin.site.site_title = 'TalentGate dev admin'
