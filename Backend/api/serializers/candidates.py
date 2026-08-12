from rest_framework import serializers

from api.models import Candidate, ExamAttempt
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


def _effective_status(candidate):
    """(status, status_display) - reflects the candidate's latest exam attempt when one
    exists, since that's more current than the static Candidate.status field.
    """
    attempt = _latest_attempt(candidate)
    if attempt and attempt.status in _ATTEMPT_STATUS_TO_CANDIDATE_STATUS:
        return _ATTEMPT_STATUS_TO_CANDIDATE_STATUS[attempt.status]
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
            'candidate_id', 'full_name', 'email', 'batch_id', 'batch_name',
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
    evidence = serializers.SerializerMethodField()
    timeline = serializers.SerializerMethodField()

    class Meta:
        model = Candidate
        fields = [
            'candidate_id', 'full_name', 'email', 'phone',
            'college_name', 'degree', 'stream', 'percentage', 'passing_out_year', 'location',
            'aadhaar_masked', 'batch_id', 'batch_name', 'status', 'status_display',
            'result', 'result_display', 'overall_score', 'section_results', 'evidence', 'timeline',
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
        return events
