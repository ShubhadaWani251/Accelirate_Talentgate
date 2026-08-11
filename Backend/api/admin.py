from django.contrib import admin
from .models import (
    Permission, Role, RolePermission,
    User, OTPVerification,
    QuestionBankSection, Question,
    Batch,
    Candidate, DuplicateCheck, Invitation,
    ExamAttempt, ExamAnswer, ProctoringEvent,
    AuditLog,
    Setting
)
from .serializers.common import mask_aadhaar



@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ['permission_code', 'module', 'description']
    search_fields = ['permission_code', 'module']
    list_filter = ['module']


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ['role_name', 'role_code', 'priority', 'is_active', 'is_system']
    search_fields = ['role_name', 'role_code']
    list_filter = ['is_active', 'is_system']


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ['role', 'permission']
    search_fields = ['role__role_name', 'permission__permission_code']
    list_filter = ['role', 'permission']


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'email', 'role', 'is_active']
    search_fields = ['first_name', 'last_name', 'email']
    list_filter = ['role', 'is_active', 'is_deleted']


@admin.register(OTPVerification)
class OTPVerificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'purpose', 'expires_at', 'verified_at']
    list_filter = ['purpose']


@admin.register(QuestionBankSection)
class QuestionBankSectionAdmin(admin.ModelAdmin):
    list_display = ['section_name', 'section_key', 'min_required_active']
    search_fields = ['section_name', 'section_key']


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ['question_code', 'section', 'difficulty', 'status', 'marks']
    search_fields = ['question_code', 'question_text']
    list_filter = ['section', 'difficulty', 'status']


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ['batch_name', 'college_name', 'status', 'total_candidates']
    search_fields = ['batch_name', 'college_name']
    list_filter = ['status', 'is_deleted']


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    # aadhaar_number is deliberately never shown unmasked here, matching the API's own
    # consistent masking (serializers/common.py) - Django admin access is governed by
    # django.contrib.auth's own is_staff flag, not this app's RBAC, so it shouldn't be a
    # backdoor to raw PII the rest of the app carefully never exposes.
    list_display = ['full_name', 'email', 'batch', 'status', 'result', 'masked_aadhaar']
    search_fields = ['first_name', 'last_name', 'email']
    list_filter = ['batch', 'status', 'result', 'validation_status']
    exclude = ['aadhaar_number']

    @admin.display(description='Aadhaar')
    def masked_aadhaar(self, obj):
        return mask_aadhaar(obj.aadhaar_number)


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ['candidate', 'batch', 'email_status', 'is_link_used']
    list_filter = ['email_status', 'is_link_used', 'is_re_invite']


@admin.register(ExamAttempt)
class ExamAttemptAdmin(admin.ModelAdmin):
    list_display = ['candidate', 'status', 'overall_score', 'started_at']
    list_filter = ['status']
    search_fields = ['candidate__email', 'candidate__first_name']


@admin.register(ExamAnswer)
class ExamAnswerAdmin(admin.ModelAdmin):
    list_display = ['attempt', 'question', 'selected_option', 'is_correct']
    list_filter = ['is_correct']


@admin.register(ProctoringEvent)
class ProctoringEventAdmin(admin.ModelAdmin):
    list_display = ['attempt', 'event_type', 'severity', 'is_violation']
    list_filter = ['event_type', 'severity', 'is_violation']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['log_id', 'user', 'action_type', 'entity_type', 'requires_review']
    list_filter = ['action_type', 'entity_type', 'requires_review']
    search_fields = ['user__email', 'entity_type']


@admin.register(Setting)
class SettingAdmin(admin.ModelAdmin):
    list_display = ['setting_key', 'setting_group', 'is_editable']
    list_filter = ['setting_group', 'is_editable']
    search_fields = ['setting_key']