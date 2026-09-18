import re

from django.conf import settings
from rest_framework import serializers

from api.models import AuditLog, Candidate, ExamAttempt, Invitation
from api.serializers.common import format_aadhaar_last4
from api.services import aadhaar, blob_storage, exam_session
from api.services.email_templates import format_datetime
from api.services.exam_session import termination_label

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

    Ordered by -attempt_id, NOT -started_at: started_at stays null until the candidate actually
    begins the timed exam (see exam_session.start_or_resume_attempt), so a candidate who
    abandoned an earlier invitation right after identity capture - then got a fresh invite and
    completed the exam on a second attempt - has one attempt with started_at=None and a LATER
    one with a real timestamp. Postgres sorts null as the "largest" value, so ORDER BY
    started_at DESC put the abandoned, evidence-less attempt first instead of the completed one
    (a real incident: a candidate's Detail page showed no photo/recording and status
    "In Progress" despite having actually finished). attempt_id is a BigAutoField, never null,
    and increases with creation order, so it can't be shadowed by an attempt that never started.
    """
    if hasattr(candidate, 'prefetched_latest_attempts'):
        attempts = candidate.prefetched_latest_attempts
        return attempts[0] if attempts else None
    if not hasattr(candidate, '_latest_attempt_cache'):
        candidate._latest_attempt_cache = (
            candidate.examattempt_set.order_by('-attempt_id').first()
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


def _latest_invitation(candidate):
    """The most recent invitation for this candidate, or None.

    Ordered by invitation_id rather than email_sent_at: a FAILED send never sets email_sent_at,
    so ordering by it would rank the newest failure below an older success and report the
    candidate as SENT when their latest attempt actually failed - the precise thing this is
    meant to surface.
    """
    if not hasattr(candidate, '_cached_latest_invitation'):
        # `.all()` reuses the prefetch cache (see views/candidates._with_latest_attempt);
        # any other queryset method would build a new query and bypass it, turning this into
        # one round-trip per row.
        invitations = list(candidate.invitation_set.all())
        candidate._cached_latest_invitation = (
            max(invitations, key=lambda inv: inv.invitation_id) if invitations else None
        )
    return candidate._cached_latest_invitation


def _email_status_display(invitation):
    """A richer label than the bare EmailStatus choice for the two states where retry_count
    actually changes what the row means: a FAILED row the sweep will keep trying looks very
    different from one it has given up on, and a SENT row that only went out after several
    automatic retries is worth knowing about even though it ended up in the same place as one
    that sent cleanly on the first try.
    """
    base = invitation.get_email_status_display()
    if invitation.email_status == Invitation.EmailStatus.FAILED:
        if invitation.retry_count >= settings.INVITE_MAX_RETRY_ATTEMPTS:
            return f'{base} (retries exhausted)'
        return f'{base} (retry pending)'
    if invitation.email_status == Invitation.EmailStatus.SENT and invitation.retry_count > 0:
        return f'{base} (after {invitation.retry_count} retr{"y" if invitation.retry_count == 1 else "ies"})'
    return base


def _email_delivery(candidate):
    """Email send state for the candidate's latest invitation.

    `status` is null when no invitation exists at all - which is different from "pending": one
    means nothing was ever attempted, the other means it is queued and in flight. The UI needs
    to tell those apart, so this does not collapse them into a single value.
    """
    if hasattr(candidate, '_cached_email_delivery'):
        return candidate._cached_email_delivery
    invitation = _latest_invitation(candidate)
    if invitation is None:
        candidate._cached_email_delivery = {
            'email_status': None,
            'email_status_display': 'Not invited',
            'email_error': None,
            'email_sent_at': None,
            'email_last_attempt_at': None,
            'retry_count': 0,
        }
        return candidate._cached_email_delivery
    candidate._cached_email_delivery = {
        'email_status': invitation.email_status,
        'email_status_display': _email_status_display(invitation),
        'email_error': invitation.email_error,
        'email_sent_at': invitation.email_sent_at,
        'email_last_attempt_at': invitation.email_last_attempt_at,
        'retry_count': invitation.retry_count,
    }
    return candidate._cached_email_delivery


class CandidateListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    aadhaar_last4 = serializers.SerializerMethodField()
    batch_name = serializers.CharField(source='batch.batch_name', read_only=True)
    # The batch's current assessment-link window, so a "resend invite" action elsewhere in the
    # UI can show/preselect it rather than sending blind - see CandidateResendInviteView, which
    # (via create_single_reinvite) always uses whatever this is AT SEND TIME, not a copy taken
    # here. Read-only: changing it goes through PATCH /batches/<id>/, same as the first send.
    link_valid_from = serializers.DateTimeField(source='batch.link_valid_from', read_only=True)
    link_valid_until = serializers.DateTimeField(source='batch.link_valid_until', read_only=True)
    status = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    result_display = serializers.CharField(source='get_result_display', read_only=True)
    logical_score = serializers.SerializerMethodField()
    quantitative_score = serializers.SerializerMethodField()
    verbal_score = serializers.SerializerMethodField()
    programming_score = serializers.SerializerMethodField()
    overall_score = serializers.SerializerMethodField()
    total_correct = serializers.SerializerMethodField()
    total_marks_earned = serializers.SerializerMethodField()
    overall_total = serializers.SerializerMethodField()
    has_attempt = serializers.SerializerMethodField()
    # Email delivery state for the latest invitation, so All Candidates can show which
    # people never actually received their link. Candidate.status flips to INVITED when the
    # invitation row is created, which is BEFORE the send is attempted - so on its own it
    # reads as success even when the email bounced.
    email_status = serializers.SerializerMethodField()
    email_status_display = serializers.SerializerMethodField()
    email_error = serializers.SerializerMethodField()
    email_sent_at = serializers.SerializerMethodField()
    email_retry_count = serializers.SerializerMethodField()

    class Meta:
        model = Candidate
        fields = [
            'candidate_id', 'full_name', 'email', 'phone', 'batch_id', 'batch_name',
            'college_name', 'degree', 'stream', 'percentage', 'passing_out_year', 'location',
            'aadhaar_last4', 'date_of_birth', 'status', 'status_display', 'result', 'result_display',
            'logical_score', 'quantitative_score', 'verbal_score', 'programming_score',
            'overall_score', 'total_correct', 'total_marks_earned', 'overall_total',
            'has_attempt',
            'email_status', 'email_status_display', 'email_error', 'email_sent_at',
            'email_retry_count', 'link_valid_from', 'link_valid_until',
        ]

    def get_aadhaar_last4(self, candidate):
        return format_aadhaar_last4(candidate.aadhaar_last4)

    def get_email_status(self, candidate):
        return _email_delivery(candidate)['email_status']

    def get_email_retry_count(self, candidate):
        return _email_delivery(candidate)['retry_count']

    def get_email_status_display(self, candidate):
        return _email_delivery(candidate)['email_status_display']

    def get_email_error(self, candidate):
        return _email_delivery(candidate)['email_error']

    def get_email_sent_at(self, candidate):
        return _email_delivery(candidate)['email_sent_at']

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
        """PERCENTAGE - see CandidateDetailSerializer.get_overall_score."""
        attempt = _latest_attempt(candidate)
        return attempt.overall_score if attempt else candidate.overall_score

    def get_total_correct(self, candidate):
        """QUESTION COUNT of correct answers. Not the Overall column's numerator - that's
        total_marks_earned, which agrees with the per-section columns beside it. Kept because
        "how many did they get right" is a separate, genuinely useful figure once marks are
        weighted, and because it is what an export consumer would expect from this name.
        """
        attempt = _latest_attempt(candidate)
        return attempt.total_correct if attempt else None

    def get_total_marks_earned(self, candidate):
        """MARKS, the numerator for the Overall column's "x/y" - matches the per-section score
        columns, which are marks too.
        """
        attempt = _latest_attempt(candidate)
        return attempt.total_marks_earned if attempt else None

    def get_overall_total(self, candidate):
        """MARKS available, off the attempt's own paper. Falls back to the batch's configured
        question counts only when there's no attempt yet - no paper has been drawn at that
        point, so its marks total doesn't exist, and with the default 1 mark per question the
        count is the right expectation to show.
        """
        attempt = _latest_attempt(candidate)
        if attempt and attempt.total_marks:
            return attempt.total_marks
        batch = candidate.batch
        return (batch.logical_questions + batch.quantitative_questions
                + batch.verbal_questions + batch.programming_questions)

    def get_has_attempt(self, candidate):
        return _latest_attempt(candidate) is not None


class CandidateUpdateSerializer(serializers.ModelSerializer):
    """`batch` stays excluded - moving a candidate between batches has its own dedicated flow.

    aadhaar_last4/date_of_birth ARE editable here even though they're the duplicate-detection
    identity key (see services/candidate_profile.link_profile and services/duplicate_check.
    run_duplicate_check) - saving a change through this endpoint does NOT re-run the duplicate
    check or re-link the candidate's CandidateProfile, so a correction here can leave both
    stale. Accepted tradeoff (TAs need to be able to fix a mistyped Aadhaar/DOB), not an
    oversight.
    """
    # The model field has blank=False, so DRF would otherwise reject '' - some existing rows
    # were uploaded with a missing Aadhaar (see Candidate.ValidationStatus.MISSING_AADHAAR) and
    # this form must still be able to save their OTHER fields without being forced to
    # backfill it first.
    aadhaar_last4 = serializers.CharField(max_length=4, allow_blank=True, required=False)

    class Meta:
        model = Candidate
        fields = [
            'first_name', 'last_name', 'email', 'phone', 'aadhaar_last4', 'date_of_birth',
            'college_name', 'degree', 'stream', 'percentage', 'passing_out_year', 'location',
        ]


class CandidateDetailSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    aadhaar_last4 = serializers.SerializerMethodField()
    batch_name = serializers.CharField(source='batch.batch_name', read_only=True)
    # See the identical fields on CandidateListSerializer - same purpose (a "resend invite"
    # action needs to show/preselect the batch's current window), same read-only caveat.
    link_valid_from = serializers.DateTimeField(source='batch.link_valid_from', read_only=True)
    link_valid_until = serializers.DateTimeField(source='batch.link_valid_until', read_only=True)
    status = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    result_display = serializers.CharField(source='get_result_display', read_only=True)
    section_results = serializers.SerializerMethodField()
    overall_score = serializers.SerializerMethodField()
    overall_total = serializers.SerializerMethodField()
    total_correct = serializers.SerializerMethodField()
    total_marks_earned = serializers.SerializerMethodField()
    evidence = serializers.SerializerMethodField()
    timeline = serializers.SerializerMethodField()
    email_status = serializers.SerializerMethodField()
    email_status_display = serializers.SerializerMethodField()
    email_error = serializers.SerializerMethodField()
    email_sent_at = serializers.SerializerMethodField()
    email_last_attempt_at = serializers.SerializerMethodField()
    email_retry_count = serializers.SerializerMethodField()
    other_batches = serializers.SerializerMethodField()
    aadhaar_hash_conflicts = serializers.SerializerMethodField()

    class Meta:
        model = Candidate
        fields = [
            'candidate_id', 'full_name', 'email', 'phone',
            'college_name', 'degree', 'stream', 'percentage', 'passing_out_year', 'location',
            'aadhaar_last4', 'date_of_birth', 'batch_id', 'batch_name', 'status', 'status_display',
            'result', 'result_display', 'overall_score', 'overall_total', 'total_correct',
            'total_marks_earned', 'section_results',
            'evidence', 'timeline',
            'email_status', 'email_status_display', 'email_error', 'email_sent_at',
            'email_last_attempt_at', 'email_retry_count',
            'link_valid_from', 'link_valid_until',
            'other_batches', 'aadhaar_hash_conflicts',
        ]

    def get_aadhaar_last4(self, candidate):
        return format_aadhaar_last4(candidate.aadhaar_last4)

    def get_email_status(self, candidate):
        return _email_delivery(candidate)['email_status']

    def get_email_status_display(self, candidate):
        return _email_delivery(candidate)['email_status_display']

    def get_email_error(self, candidate):
        return _email_delivery(candidate)['email_error']

    def get_email_sent_at(self, candidate):
        return _email_delivery(candidate)['email_sent_at']

    def get_email_last_attempt_at(self, candidate):
        return _email_delivery(candidate)['email_last_attempt_at']

    def get_email_retry_count(self, candidate):
        return _email_delivery(candidate)['retry_count']

    def get_status(self, candidate):
        return _effective_status(candidate)[0]

    def get_status_display(self, candidate):
        return _effective_status(candidate)[1]

    def get_overall_score(self, candidate):
        """PERCENTAGE, not a mark count - pair it with `%`, never with overall_total."""
        attempt = _latest_attempt(candidate)
        return attempt.overall_score if attempt else candidate.overall_score

    def get_total_correct(self, candidate):
        """QUESTION COUNT of correct answers. Its own figure, no longer the numerator for
        "x/overall_total" - see get_total_marks_earned, which is.
        """
        attempt = _latest_attempt(candidate)
        return attempt.total_correct if attempt else None

    def get_total_marks_earned(self, candidate):
        """MARKS earned - the numerator for the "14/40" reading on Candidate Details.

        Separate from overall_score, which is a PERCENTAGE: the UI once rendered that over
        overall_total, so 2 out of 40 displayed as "5/40".
        """
        attempt = _latest_attempt(candidate)
        return attempt.total_marks_earned if attempt else None

    def get_overall_total(self, candidate):
        """MARKS available - the denominator for that "14/40" reading, taken from the
        attempt's own paper rather than the batch's question counts, which are only the same
        number while every question is worth 1 mark. Falls back to the counts when no attempt
        exists yet, since there is no paper to total at that point.
        """
        attempt = _latest_attempt(candidate)
        if attempt and attempt.total_marks:
            return attempt.total_marks
        batch = candidate.batch
        return (batch.logical_questions + batch.quantitative_questions
                + batch.verbal_questions + batch.programming_questions)

    def get_section_results(self, candidate):
        attempt = _latest_attempt(candidate)
        batch = candidate.batch
        # One extra query, on a single-candidate detail response only - never inside a list
        # loop. Needed because the per-section denominator is the marks on this candidate's own
        # paper, which lives on their ExamAnswer rows rather than on the attempt.
        marks_by_section = (
            exam_session.section_marks_for_attempt(attempt) if attempt else {}
        )
        rows = []
        for key, label in SECTION_LABELS.items():
            score = getattr(attempt, f'{key}_score', None) if attempt else None
            cleared = getattr(attempt, f'{key}_cleared', None) if attempt else None
            rows.append({
                'section': label,
                # MARKS, matching `total` below - not a count of correct answers.
                'score': score,
                # Per-section denominator, in marks. Sent explicitly because the UI previously
                # hardcoded "/10", which silently showed a wrong total for any batch not
                # configured with exactly 10 questions per section. Falls back to the batch's
                # question count when there's no attempt, where there is no paper to total.
                'total': (marks_by_section.get(key, (0, 0))[1] if attempt
                          else getattr(batch, f'{key}_questions')),
                'cutoff': float(getattr(batch, f'{key}_cutoff')),
                'cleared': cleared,
            })
        return rows

    def get_other_batches(self, candidate):
        """This person's other batch appearances, same real-person identity (see
        services/candidate_profile.py) - empty when this row has no profile (no Aadhaar to key
        on) or the profile has no other memberships. Each entry links to that OTHER candidate
        row's own detail page; nothing here is merged or deleted, just surfaced.
        """
        if not candidate.profile_id:
            return []
        others = (
            candidate.profile.memberships
            .exclude(candidate_id=candidate.candidate_id)
            .exclude(is_deleted=True)
            .select_related('batch')
            .order_by('-created_at')
        )
        return [
            {
                'candidate_id': other.candidate_id,
                'batch_name': other.batch.batch_name,
                'created_at': other.created_at,
                'result': other.result,
                'result_display': other.get_result_display(),
                'overall_score': other.overall_score,
            }
            for other in others
        ]

    def get_aadhaar_hash_conflicts(self, candidate):
        """Other candidates whose decoded Aadhaar photo hashes to the same value as this one's -
        see services.aadhaar.find_hash_conflicts for why this is a read-time, post-hoc signal,
        never a gate, and unrelated to the pre-exam duplicate_check.py system.
        """
        attempt = _latest_attempt(candidate)
        return aadhaar.find_hash_conflicts(attempt) if attempt else []

    def get_evidence(self, candidate):
        attempt = _latest_attempt(candidate)
        if not attempt:
            return {
                'aadhaar_capture_url': None, 'aadhaar_capture_download_url': None,
                'face_photo_url': None, 'face_photo_download_url': None,
                'session_recording_url': None, 'session_recording_download_url': None,
                'session_recording_mp4_url': None, 'session_recording_mp4_download_url': None,
                'aadhaar_verification_status': None, 'aadhaar_verification_status_display': None,
                'aadhaar_decoded_last4': None,
            }
        # Signed here, at the moment they are handed to the browser, rather than read straight
        # off the row. The stored values are unsigned pointers and would 404 on their own; each
        # URL returned below carries a token valid for a couple of hours. See
        # services/blob_storage.fresh_read_url for why the credential is not persisted.
        #
        # Two URLs per file, not one: the *_url fields open inline for "View Full Image"/"Play
        # Recording", while *_download_url carries a Content-Disposition: attachment override so
        # the browser actually saves the file for "Download" - the plain HTML `download`
        # attribute a candidate's own <a> tag would otherwise rely on is silently ignored by
        # every major browser for a cross-origin URL (which a blob storage URL always is), so
        # those buttons did nothing before this.
        # Stripped to filename-safe ASCII: a candidate name can carry quotes, commas or
        # non-ASCII characters, any of which would either break the Content-Disposition header
        # syntax or need RFC 5987 encoding this doesn't attempt. Falls back to the candidate id
        # if that strips the name down to nothing.
        candidate_slug = re.sub(r'[^A-Za-z0-9]+', '_', candidate.full_name).strip('_')
        candidate_slug = candidate_slug or str(candidate.candidate_id)
        return {
            'aadhaar_capture_url': blob_storage.fresh_read_url(attempt.aadhaar_capture_url),
            'aadhaar_capture_download_url': blob_storage.fresh_read_url(
                attempt.aadhaar_capture_url, download_filename=f'{candidate_slug}_aadhaar.jpg',
            ),
            'face_photo_url': blob_storage.fresh_read_url(attempt.face_photo_url),
            'face_photo_download_url': blob_storage.fresh_read_url(
                attempt.face_photo_url, download_filename=f'{candidate_slug}_face_photo.jpg',
            ),
            'session_recording_url': blob_storage.fresh_read_url(attempt.session_recording_url),
            'session_recording_download_url': blob_storage.fresh_read_url(
                attempt.session_recording_url,
                download_filename=f'{candidate_slug}_session_recording.webm',
            ),
            # Null until services.video_transcode has converted it (see
            # management/commands/transcode_recordings.py) - the frontend shows this pair only
            # once session_recording_mp4_url is actually present, same "null means not ready/not
            # applicable yet" convention as every evidence field above.
            'session_recording_mp4_url': blob_storage.fresh_read_url(
                attempt.session_recording_mp4_url,
            ),
            'session_recording_mp4_download_url': blob_storage.fresh_read_url(
                attempt.session_recording_mp4_url,
                download_filename=f'{candidate_slug}_session_recording.mp4',
            ),
            'aadhaar_verification_status': attempt.aadhaar_verification_status,
            'aadhaar_verification_status_display': attempt.get_aadhaar_verification_status_display(),
            'aadhaar_decoded_last4': attempt.aadhaar_decoded_last4,
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
                    # format_datetime, not a bare .strftime() on the stored value. Timestamps
                    # are stored in UTC (settings.TIME_ZONE), so strftime rendered this 5h30m
                    # behind the IST times shown in the same table's own Date/Time column - an
                    # invite sent at 03:01 pm read "Link valid until 11:30 AM", i.e. apparently
                    # expiring before it was sent. Same bug, and the same fix, as the one
                    # format_datetime's own docstring describes for candidate emails; the zone
                    # is named in the output so the reader never has to assume which one it is.
                    'details': f'Link valid until {format_datetime(invitation.link_expired_at)}',
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
                events.append({
                    'timestamp': attempt.started_at,
                    'event': 'Started',
                    # Same idea as the Terminated row's label below - a TA-facing fact worth
                    # surfacing, not something the candidate ever sees. Only ever set, never
                    # cleared (services.seb.record_seb_usage), so this is safe to trust: it
                    # never claims SEB when a fallback candidate is who actually started.
                    'details': 'Via Safe Exam Browser' if attempt.seb_verified_at else None,
                })
            if attempt.submitted_at:
                events.append({'timestamp': attempt.submitted_at, 'event': 'Submitted', 'details': None})
            if attempt.terminated_at:
                events.append({
                    'timestamp': attempt.terminated_at,
                    'event': 'Terminated',
                    # Readable label, not the raw stored code - this cell is read by a TA.
                    'details': termination_label(attempt.termination_reason),
                })

        # Newest first. NOTE there are two history renderings and they must agree: this one
        # (Candidate Details -> Process / Status History) and services/candidate_history.py
        # (the upload History modal). Only the latter was reordered at first, so this table
        # kept showing oldest-first while the modal showed newest-first.
        events.sort(key=lambda e: e['timestamp'], reverse=True)
        # Every event on this screen belongs to the candidate's own batch (unlike the upload
        # History modal, which spans the duplicate-matched record too). Stamped once here so
        # the table's Batch column doesn't need it repeated at each append site above.
        batch_name = candidate.batch.batch_name
        for event in events:
            event['batch_name'] = batch_name
        return events
