from rest_framework import serializers

from api.models import AuditLog, Candidate, ExamAttempt
from api.serializers.common import mask_aadhaar

SECTION_LABELS = {
    'logical': 'Logical & Analytical',
    'quantitative': 'Quantitative',
    'verbal': 'Verbal Ability',
    'programming': 'Programming',
}

# Maps an in-flight ExamAttempt's own status onto the equivalent Candidate.Status value/label -
# nothing in the codebase yet writes IN_PROGRESS/COMPLETED/TERMINATED back onto Candidate.status
# itself (that requires the exam-taking flow, a later phase), so this derives the same
# information at read time from data that's already loaded for the score columns.
_ATTEMPT_STATUS_TO_CANDIDATE_STATUS = {
    ExamAttempt.Status.IN_PROGRESS: (Candidate.Status.IN_PROGRESS, 'In Progress'),
    ExamAttempt.Status.SUBMITTED: (Candidate.Status.COMPLETED, 'Completed'),
    ExamAttempt.Status.TERMINATED: (Candidate.Status.TERMINATED, 'Terminated'),
}


def _latest_attempt(candidate):
    """Per-instance cached lookup, same pattern as CandidateStagingSerializer._latest_check.
    Prefers a bulk-fetched `prefetched_latest_attempts` list (set by views/candidates.py's
    `_with_latest_attempt`) over the per-instance query, to avoid N+1 across a list response.
    """
    if hasattr(candidate, 'prefetched_latest_attempts'):
        attempts = candidate.prefetched_latest_attempts
        return attempts[0] if attempts else None
    if not hasattr(candidate, '_latest_attempt_cache'):
        candidate._latest_attempt_cache = (
            candidate.examattempt_set.order_by('-started_at').first()
        )
    return candidate._latest_attempt_cache


# Outreach actions that should be visible in the Status column. Candidate.status itself only
# ever moves pending_invite -> invited, so without this a TA sees no difference between a
# candidate they've merely invited and one they've since notified or sent certification links
# to. These are display-only: the stored status stays the pipeline value, so a bulk send can't
# overwrite real state.
_ACTIVITY_STATUS_LABELS = {
    'certification_sent': 'Certification Sent',
    'notify_sent': 'Notification Sent',
    'invite_sent': 'Invited',
}


def _latest_activity(candidate):
    """Most recent outreach audit row for this candidate.

    Prefers the bulk-attached `prefetched_latest_activity` (set by views/candidates.py's
    `attach_latest_activity`) so a list response doesn't fire one query per row - the same
    N+1 guard `_latest_attempt` uses.
    """
    if hasattr(candidate, 'prefetched_latest_activity'):
        return candidate.prefetched_latest_activity
    if not hasattr(candidate, '_latest_activity_cache'):
        candidate._latest_activity_cache = (
            AuditLog.objects
            .filter(entity_type='candidate', entity_id=candidate.candidate_id,
                    action_type__in=_ACTIVITY_STATUS_LABELS)
            .order_by('-created_at')
            .first()
        )
    return candidate._latest_activity_cache


def _effective_status(candidate):
    """(status, status_display) for the Status column.

    Precedence: a real exam attempt beats everything, because where the candidate actually got
    to matters more than what we last emailed them. Failing that, the most recent outreach
    action is shown, so notifications and certification sends are visible rather than silently
    leaving the row reading "Invited". The returned status *code* stays the stored pipeline
    value - only the label changes - so the pill colour and any client-side filtering on
    status keep working.
    """
    attempt = _latest_attempt(candidate)
    if attempt and attempt.status in _ATTEMPT_STATUS_TO_CANDIDATE_STATUS:
        return _ATTEMPT_STATUS_TO_CANDIDATE_STATUS[attempt.status]

    activity = _latest_activity(candidate)
    if activity:
        label = _ACTIVITY_STATUS_LABELS.get(activity.action_type)
        if activity.action_type == 'invite_sent' and (activity.action_details or {}).get('re_invite'):
            label = 'Invite Re-sent'
        if label:
            return candidate.status, label

    return candidate.status, candidate.get_status_display()


class CandidateListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    aadhaar_masked = serializers.SerializerMethodField()
    batch_name = serializers.CharField(source='batch.batch_name', read_only=True)
    status = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    result_display = serializers.CharField(source='get_result_display', read_only=True)
    logical_score = serializers.SerializerMethodField()
    quantitative_score = serializers.SerializerMethodField()
    verbal_score = serializers.SerializerMethodField()
    programming_score = serializers.SerializerMethodField()
    overall_score = serializers.SerializerMethodField()
    has_attempt = serializers.SerializerMethodField()

    class Meta:
        model = Candidate
        fields = [
            'candidate_id', 'full_name', 'email', 'phone', 'batch_id', 'batch_name',
            'college_name', 'degree', 'stream', 'percentage', 'passing_out_year', 'location',
            'aadhaar_masked', 'status', 'status_display', 'result', 'result_display',
            'logical_score', 'quantitative_score', 'verbal_score', 'programming_score',
            'overall_score', 'has_attempt',
        ]

    def get_aadhaar_masked(self, candidate):
        return mask_aadhaar(candidate.aadhaar_number)

    def get_status(self, candidate):
        return _effective_status(candidate)[0]

    def get_status_display(self, candidate):
        return _effective_status(candidate)[1]

    def get_logical_score(self, candidate):
        attempt = _latest_attempt(candidate)
        return attempt.logical_score if attempt else None

    def get_quantitative_score(self, candidate):
        attempt = _latest_attempt(candidate)
        return attempt.quantitative_score if attempt else None

    def get_verbal_score(self, candidate):
        attempt = _latest_attempt(candidate)
        return attempt.verbal_score if attempt else None

    def get_programming_score(self, candidate):
        attempt = _latest_attempt(candidate)
        return attempt.programming_score if attempt else None

    def get_overall_score(self, candidate):
        attempt = _latest_attempt(candidate)
        return attempt.overall_score if attempt else candidate.overall_score

    def get_has_attempt(self, candidate):
        return _latest_attempt(candidate) is not None


class CandidateUpdateSerializer(serializers.ModelSerializer):
    """Deliberately excludes aadhaar_number and batch - changing either would silently
    invalidate the duplicate-check that already ran against this candidate's current values.
    """
    class Meta:
        model = Candidate
        fields = [
            'first_name', 'last_name', 'email', 'phone',
            'college_name', 'degree', 'stream', 'percentage', 'passing_out_year', 'location',
        ]


class CandidateDetailSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    aadhaar_masked = serializers.SerializerMethodField()
    batch_name = serializers.CharField(source='batch.batch_name', read_only=True)
    status = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    result_display = serializers.CharField(source='get_result_display', read_only=True)
    section_results = serializers.SerializerMethodField()
    overall_score = serializers.SerializerMethodField()
    overall_total = serializers.SerializerMethodField()
    evidence = serializers.SerializerMethodField()
    timeline = serializers.SerializerMethodField()

    class Meta:
        model = Candidate
        fields = [
            'candidate_id', 'full_name', 'email', 'phone',
            'college_name', 'degree', 'stream', 'percentage', 'passing_out_year', 'location',
            'aadhaar_masked', 'batch_id', 'batch_name', 'status', 'status_display',
            'result', 'result_display', 'overall_score', 'overall_total', 'section_results',
            'evidence', 'timeline',
        ]

    def get_aadhaar_masked(self, candidate):
        return mask_aadhaar(candidate.aadhaar_number)

    def get_status(self, candidate):
        return _effective_status(candidate)[0]

    def get_status_display(self, candidate):
        return _effective_status(candidate)[1]

    def get_overall_score(self, candidate):
        attempt = _latest_attempt(candidate)
        return attempt.overall_score if attempt else candidate.overall_score

    def get_overall_total(self, candidate):
        """Denominator for the "14/40" reading on Candidate Details - one mark per question,
        so it's the batch's four section counts added up.
        """
        batch = candidate.batch
        return (batch.logical_questions + batch.quantitative_questions
                + batch.verbal_questions + batch.programming_questions)

    def get_section_results(self, candidate):
        attempt = _latest_attempt(candidate)
        batch = candidate.batch
        rows = []
        for key, label in SECTION_LABELS.items():
            score = getattr(attempt, f'{key}_score', None) if attempt else None
            cleared = getattr(attempt, f'{key}_cleared', None) if attempt else None
            rows.append({
                'section': label,
                'score': score,
                'cutoff': float(getattr(batch, f'{key}_cutoff')),
                'cleared': cleared,
            })
        return rows

    def get_evidence(self, candidate):
        attempt = _latest_attempt(candidate)
        if not attempt:
            return {
                'aadhaar_capture_url': None,
                'face_photo_url': None,
                'session_recording_url': None,
            }
        return {
            'aadhaar_capture_url': attempt.aadhaar_capture_url,
            'face_photo_url': attempt.face_photo_url,
            'session_recording_url': attempt.session_recording_url,
        }

    def get_timeline(self, candidate):
        events = [{
            'timestamp': candidate.created_at,
            'event': 'Uploaded',
            'details': (
                f'Bulk upload — Row {candidate.upload_row_number}'
                if candidate.upload_row_number else 'Uploaded'
            ),
        }]

        latest_check = candidate.duplicate_checks.order_by('-checked_at').first()
        if latest_check:
            events.append({
                'timestamp': latest_check.checked_at,
                'event': 'Duplicate Check',
                'details': latest_check.get_check_status_display(),
            })

        for invitation in candidate.invitation_set.order_by('email_sent_at'):
            if invitation.email_sent_at:
                events.append({
                    'timestamp': invitation.email_sent_at,
                    'event': 'Invite Re-sent' if invitation.is_re_invite else 'Invite Sent',
                    'details': (
                        f'Link valid until '
                        f'{invitation.link_expired_at.strftime("%d-%b-%Y %I:%M %p")}'
                    ),
                })
            if invitation.link_clicked_at:
                events.append({
                    'timestamp': invitation.link_clicked_at,
                    'event': 'Link Clicked',
                    'details': None,
                })

        attempt = _latest_attempt(candidate)
        if attempt:
            if attempt.started_at:
                events.append({'timestamp': attempt.started_at, 'event': 'Started', 'details': None})
            if attempt.submitted_at:
                events.append({'timestamp': attempt.submitted_at, 'event': 'Submitted', 'details': None})
            if attempt.terminated_at:
                events.append({
                    'timestamp': attempt.terminated_at,
                    'event': 'Terminated',
                    'details': attempt.termination_reason,
                })

        events.sort(key=lambda e: e['timestamp'])
        # Every event on this screen belongs to the candidate's own batch (unlike the upload
        # History modal, which spans the duplicate-matched record too). Stamped once here so
        # the table's Batch column doesn't need it repeated at each append site above.
        batch_name = candidate.batch.batch_name
        for event in events:
            event['batch_name'] = batch_name
        return events
