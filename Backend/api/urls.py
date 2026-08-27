# api/urls.py
from django.urls import path

from . import views

urlpatterns = [
    path('health/', views.health_check, name='health'),
    # Separate from liveness above: this one fails when the database is unreachable, so a
    # load balancer stops sending traffic to an instance that cannot serve it.
    path('health/ready/', views.readiness_check, name='health-ready'),

    path('auth/login/', views.LoginView.as_view(), name='auth-login'),
    path('auth/logout/', views.LogoutView.as_view(), name='auth-logout'),
    path('auth/refresh/', views.RefreshView.as_view(), name='auth-refresh'),
    path('auth/forgot-password/', views.ForgotPasswordView.as_view(), name='auth-forgot-password'),
    path('auth/resend-otp/', views.ResendOtpView.as_view(), name='auth-resend-otp'),
    path('auth/verify-otp/', views.VerifyOtpResetView.as_view(), name='auth-verify-otp'),
    path('auth/change-password/', views.ChangePasswordView.as_view(), name='auth-change-password'),
    path('auth/me/', views.MeView.as_view(), name='auth-me'),

    path('batches/', views.BatchListCreateView.as_view(), name='batch-list-create'),
    path('batches/defaults/', views.BatchDefaultsView.as_view(), name='batch-defaults'),
    path('batches/template/', views.BatchTemplateDownloadView.as_view(), name='batch-template'),
    path('batches/<int:batch_id>/', views.BatchDetailView.as_view(), name='batch-detail'),
    path('batches/<int:batch_id>/deactivate/', views.BatchDeactivateView.as_view(),
         name='batch-deactivate'),
    path('batches/<int:batch_id>/complete/', views.BatchCompleteView.as_view(),
         name='batch-complete'),
    path('batches/<int:batch_id>/upload/', views.BatchUploadView.as_view(), name='batch-upload'),
    path('batches/<int:batch_id>/candidates/', views.BatchCandidatesStagingView.as_view(),
         name='batch-candidates'),
    path('batches/<int:batch_id>/candidates/delete/', views.BatchCandidateDeleteView.as_view(),
         name='batch-candidates-delete'),
    path('batches/<int:batch_id>/candidates/validation-report/',
         views.BatchValidationReportView.as_view(), name='batch-validation-report'),
    path('batches/<int:batch_id>/candidates/<int:candidate_id>/',
         views.BatchCandidateRowView.as_view(), name='batch-candidate-row'),
    path('batches/<int:batch_id>/candidates/<int:candidate_id>/clear-duplicate/',
         views.BatchCandidateClearDuplicateView.as_view(), name='batch-candidate-clear-duplicate'),
    path('batches/<int:batch_id>/finalize/', views.BatchFinalizeView.as_view(), name='batch-finalize'),
    path('batches/<int:batch_id>/send-invites/', views.BatchSendInvitesView.as_view(),
         name='batch-send-invites'),

    path('dashboard/', views.DashboardSummaryView.as_view(), name='dashboard-summary'),

    # Read-only oversight screen (admin only). Append-only by design - there is
    # deliberately no write endpoint for audit rows.
    path('audit-logs/', views.AuditLogListView.as_view(), name='audit-log-list'),
    path('audit-logs/filters/', views.AuditLogFilterOptionsView.as_view(),
         name='audit-log-filters'),

    path('candidates/', views.CandidateListView.as_view(), name='candidate-list'),
    path('candidates/export/', views.CandidateExportView.as_view(), name='candidate-export'),
    path('candidates/notify/', views.CandidateNotifyView.as_view(), name='candidate-notify'),
    path('candidates/resend-invite/', views.CandidateBulkResendInviteView.as_view(),
         name='candidate-bulk-resend-invite'),
    path('candidates/send-certification/', views.CandidateCertificationView.as_view(),
         name='candidate-send-certification'),
    path('candidates/notify/templates/', views.NotificationTemplateListView.as_view(),
         name='candidate-notify-templates'),
    path('candidates/<int:candidate_id>/', views.CandidateDetailView.as_view(), name='candidate-detail'),
    path('candidates/<int:candidate_id>/history/', views.CandidateHistoryView.as_view(),
         name='candidate-history'),
    path('candidates/<int:candidate_id>/resend-invite/', views.CandidateResendInviteView.as_view(),
         name='candidate-resend-invite'),
    path('candidates/<int:candidate_id>/evidence.zip', views.CandidateEvidenceZipView.as_view(),
         name='candidate-evidence-zip'),

    path('questions/', views.QuestionListCreateView.as_view(), name='question-list-create'),
    path('questions/sections/', views.QuestionSectionListView.as_view(), name='question-sections'),
    path('questions/template/', views.QuestionTemplateDownloadView.as_view(), name='question-template'),
    path('questions/upload/', views.QuestionBulkUploadView.as_view(), name='question-upload'),
    path('questions/validate-rows/', views.QuestionRowValidationView.as_view(),
         name='question-validate-rows'),
    path('questions/<int:question_id>/', views.QuestionDetailView.as_view(), name='question-detail'),

    path('users/', views.UserListCreateView.as_view(), name='user-list-create'),
    path('users/<int:user_id>/', views.UserDetailView.as_view(), name='user-detail'),

    # Candidate exam-taking portal - public up through identity capture, then authenticated via
    # the attempt JWT (CandidateAttemptAuthentication), never CustomJWTAuthentication.
    path('exam/token/<str:token>/', views.ExamTokenLandingView.as_view(), name='exam-token-landing'),
    path('exam/token/<str:token>/verify-email/', views.ExamVerifyEmailView.as_view(),
         name='exam-verify-email'),
    path('exam/token/<str:token>/identity/', views.ExamIdentityCaptureView.as_view(),
         name='exam-identity'),
    path('exam/begin/', views.ExamBeginView.as_view(), name='exam-begin'),
    path('exam/session/', views.ExamSessionView.as_view(), name='exam-session'),
    path('exam/answers/<int:question_id>/', views.ExamAnswerView.as_view(), name='exam-answer'),
    path('exam/recording/chunk/', views.ExamRecordingChunkView.as_view(), name='exam-recording-chunk'),
    path('exam/violation/', views.ExamViolationView.as_view(), name='exam-violation'),
    path('exam/submit/', views.ExamSubmitView.as_view(), name='exam-submit'),
]
