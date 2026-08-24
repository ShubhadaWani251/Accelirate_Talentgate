from django.db.models import Count, Q
from rest_framework import serializers

from api.models import Batch, Candidate, DuplicateCheck
from api.serializers.common import format_aadhaar_last4
from api.services import draft_expiry
from api.services.batch_defaults import get_batch_defaults


SECTION_FIELDS = ['logical', 'quantitative', 'verbal', 'programming']


def link_window_error(link_from, link_until, duration):
    """None if the assessment link window is at least as long as the exam, else an error string.

    Shared between BatchSerializer.validate (the PATCH that sets the window, on the wizard's
    Review & Send Invite step) and BatchFinalizeView (the last point before invites can go out) -
    one call site setting the window and a different one gating the send both need the identical
    rule, and a caller that skipped the PATCH must not be able to finalize with no window at all.

    Returns None (not raising) when any input is missing, so callers decide for themselves
    whether "unset" is acceptable at that point in the flow - it is fine mid-PATCH-validation
    (see validate()'s own touches_window/link_from/link_until/duration guard) and never fine at
    finalize, which checks for None explicitly before ever calling this.
    """
    if not (link_from and link_until and duration):
        return None
    window_minutes = (link_until - link_from).total_seconds() / 60
    if window_minutes >= duration:
        return None
    return (
        f'The link window is {int(window_minutes)} minutes, which is shorter than the '
        f'{duration}-minute exam. A candidate who needs to reconnect mid-exam would be locked '
        f'out while their timer is still running. Extend the end time to at least {duration} '
        f'minutes after the start.'
    )


def annotate_batch_counts(queryset):
    """Pass/fail counts as one annotated query instead of two `.filter().count()` queries per
    batch - callers that list many batches (BatchListCreateView, the dashboard summary) should
    always apply this before serializing; BatchSerializer falls back to the per-instance query
    when it isn't (e.g. a freshly created/updated single Batch), which is fine since that's
    only ever one instance at a time, never a list.
    """
    return queryset.annotate(
        pass_count=Count('candidate', filter=Q(candidate__result=Candidate.Result.PASS,
                                                candidate__is_deleted=False)),
        fail_count=Count('candidate', filter=Q(candidate__result=Candidate.Result.FAIL,
                                                candidate__is_deleted=False)),
    )


class BatchSerializer(serializers.ModelSerializer):
    """Used for both create (Configure Batch step) and edit (Batch Details screen)."""
    primary_ta_user_name = serializers.CharField(source='primary_ta_user.full_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    pass_count = serializers.SerializerMethodField()
    fail_count = serializers.SerializerMethodField()
    borderline_count = serializers.SerializerMethodField()
    draft_expires_at = serializers.SerializerMethodField()

    class Meta:
        model = Batch
        fields = [
            'batch_id', 'batch_name', 'college_name',
            'link_valid_from', 'link_valid_until', 'exam_duration_minutes',
            'logical_questions', 'quantitative_questions', 'verbal_questions', 'programming_questions',
            'logical_cutoff', 'quantitative_cutoff', 'verbal_cutoff', 'programming_cutoff',
            'status', 'status_display', 'total_candidates',
            'primary_ta_user', 'primary_ta_user_name', 'created_at', 'draft_expires_at',
            'pass_count', 'fail_count', 'borderline_count',
        ]
        read_only_fields = [
            'batch_id', 'status', 'status_display', 'total_candidates',
            'primary_ta_user', 'primary_ta_user_name', 'created_at', 'draft_expires_at',
            # The exam schedule and question counts are set once, org-wide, on the admin-only
            # Configure Default Batch screen (services/batch_defaults.py) and snapshotted onto
            # each batch at creation (BatchListCreateView.post) - never client-writable, at
            # creation or afterwards. Cutoffs are the one exception: they stay writable so a TA
            # can revise them after a finalized batch's cohort has been scored (see
            # ConfigureBatchStep's cutoffs-only edit mode) - creation still snapshots them from
            # the same defaults, but that happens server-side via explicit save() kwargs, not
            # through this required-ness setting.
            'exam_duration_minutes', 'logical_questions', 'quantitative_questions',
            'verbal_questions', 'programming_questions',
        ]

    def get_draft_expires_at(self, batch):
        """When an unfinalized draft will be deleted - null for every other status.

        Derived from created_at, not stored, so there's no second copy of the deadline that
        could drift from the one the cleanup job actually enforces. The UI counts down against
        this; it is informational only (see services/draft_expiry.py).
        """
        expires_at = draft_expiry.draft_expires_at(batch)
        return expires_at.isoformat() if expires_at else None

    def get_pass_count(self, batch):
        if hasattr(batch, 'pass_count'):
            return batch.pass_count
        return batch.candidate_set.filter(result=Candidate.Result.PASS, is_deleted=False).count()

    def get_fail_count(self, batch):
        if hasattr(batch, 'fail_count'):
            return batch.fail_count
        return batch.candidate_set.filter(result=Candidate.Result.FAIL, is_deleted=False).count()

    def get_borderline_count(self, batch):
        # No real exam scoring exists yet (that's Phase 4) - always 0 for now, kept here so
        # the frontend table shape doesn't need to change once scoring lands.
        return 0

    def validate(self, attrs):
        link_from = attrs.get('link_valid_from', getattr(self.instance, 'link_valid_from', None))
        link_until = attrs.get('link_valid_until', getattr(self.instance, 'link_valid_until', None))
        if link_from and link_until and link_until <= link_from:
            raise serializers.ValidationError(
                {'link_valid_until': 'Must be after Link Valid From.'}
            )

        # The link window has to be at least as long as the exam itself.
        #
        # This is not about the exam being cut short - it isn't. The deadline is
        # started_at + exam_duration_minutes and is independent of link expiry, so a candidate who
        # starts one minute before the window closes still gets their full time.
        #
        # The failure it prevents is on RESUME. Reconnecting after a dropped connection or a
        # browser crash goes back through /t/<token>, which refuses an expired link - so a
        # candidate whose exam is still legitimately running would be locked out of it while
        # their clock keeps counting down, and nothing can let them back in. A window shorter
        # than the exam guarantees a span where that is true for everyone still working.
        #
        # It is also, in practice, always a data-entry slip: a 26-minute window on a 45-minute
        # exam is someone mistyping the end time, not a deliberate choice.
        # Only enforced when the request actually touches one of the three fields involved.
        # Checking unconditionally would retroactively fail edits to batches that already
        # violate the rule - and one live batch does (a 26-minute window on a 45-minute exam,
        # created before this validation existed). Its status allows only the section cutoffs to
        # be changed, so an unconditional check would have blocked the single edit still
        # permitted on it, for a reason the TA could not act on. Grandfathering the existing row
        # while refusing to create or worsen one is the useful behaviour.
        # exam_duration_minutes is read-only (see Meta.read_only_fields), so it never appears in
        # attrs regardless of what the request sent - attrs.get() alone would silently resolve to
        # None on every create, since there's no instance yet either, and this check would never
        # fire for a create that supplied link dates directly. Falling back to the org-wide
        # default predicts the actual value BatchListCreateView.post is about to snapshot, which
        # is what will really end up on the row.
        touches_window = {'link_valid_from', 'link_valid_until'} & set(attrs)
        duration = (
            self.instance.exam_duration_minutes if self.instance
            else get_batch_defaults()['exam_duration_minutes']
        )
        if touches_window:
            error = link_window_error(link_from, link_until, duration)
            if error:
                raise serializers.ValidationError({'link_valid_until': error})
        for section in SECTION_FIELDS:
            count_field = f'{section}_questions'
            cutoff_field = f'{section}_cutoff'
            if count_field in attrs and attrs[count_field] <= 0:
                raise serializers.ValidationError({count_field: 'Must be at least 1.'})
            if cutoff_field in attrs and not (0 <= attrs[cutoff_field] <= 100):
                raise serializers.ValidationError({cutoff_field: 'Must be between 0 and 100.'})
        return attrs


class BatchDefaultsSerializer(serializers.Serializer):
    """Org-wide default exam config, backed by the Setting key/value table (setting_group='exam_config').
    Saving these only affects batches created AFTER the save - each Batch snapshots its own
    copy of these values at creation time.
    """
    exam_duration_minutes = serializers.IntegerField(min_value=1)
    logical_questions = serializers.IntegerField(min_value=1)
    quantitative_questions = serializers.IntegerField(min_value=1)
    verbal_questions = serializers.IntegerField(min_value=1)
    programming_questions = serializers.IntegerField(min_value=1)
    logical_cutoff = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100)
    quantitative_cutoff = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100)
    verbal_cutoff = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100)
    programming_cutoff = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100)


class CandidateStagingSerializer(serializers.ModelSerializer):
    """One row in the Upload Review table.

    Carries the editable template fields as well as the display ones, because each row can be
    corrected in place on this screen rather than by fixing the spreadsheet and re-uploading.
    Aadhaar is no longer masked, because only its last 4 digits are stored at all (see
    models/candidate.py) - there is nothing left to hide, and the reviewer needs to see the
    value to correct a mistyped one.
    """
    full_name = serializers.CharField(read_only=True)
    aadhaar_last4 = serializers.SerializerMethodField()
    validation_status_display = serializers.CharField(source='get_validation_status_display', read_only=True)
    duplicate_status = serializers.SerializerMethodField()
    duplicate_status_display = serializers.SerializerMethodField()
    last_attempt = serializers.SerializerMethodField()
    errors = serializers.SerializerMethodField()
    error_fields = serializers.SerializerMethodField()

    class Meta:
        model = Candidate
        fields = [
            'candidate_id', 'upload_row_number', 'full_name', 'email', 'aadhaar_last4',
            'validation_status', 'validation_status_display',
            'duplicate_status', 'duplicate_status_display', 'last_attempt',
            'errors', 'error_fields',
            # Editable template fields, for the in-place edit form.
            'first_name', 'last_name', 'phone', 'college_name', 'degree', 'stream',
            'percentage', 'passing_out_year', 'location',
        ]

    def get_aadhaar_last4(self, candidate):
        return format_aadhaar_last4(candidate.aadhaar_last4)

    def get_errors(self, candidate):
        return [e['message'] for e in (candidate.validation_errors or [])]

    def get_error_fields(self, candidate):
        return [e['field'] for e in (candidate.validation_errors or [])]

    def _latest_check(self, candidate):
        """Most recent duplicate check for this candidate.

        Picks the max out of the prefetched list rather than calling `.order_by().first()`:
        any queryset method builds a NEW queryset and silently bypasses the prefetch cache,
        which turned this into one query per row (63 rows -> 66 queries, ~16s against a remote
        database). `.all()` on a prefetched related manager reuses the cache.
        """
        if not hasattr(candidate, '_latest_dup_check'):
            candidate._latest_dup_check = max(
                candidate.duplicate_checks.all(),
                key=lambda check: check.checked_at,
                default=None,
            )
        return candidate._latest_dup_check

    def get_duplicate_status(self, candidate):
        check = self._latest_check(candidate)
        return check.check_status if check else None

    def get_duplicate_status_display(self, candidate):
        check = self._latest_check(candidate)
        return check.get_check_status_display() if check else None

    def get_last_attempt(self, candidate):
        check = self._latest_check(candidate)
        if not check or not check.existing_candidate:
            return None
        return {
            'batch_name': check.existing_candidate.batch.batch_name,
            'date': check.existing_attempt_date,
        }
