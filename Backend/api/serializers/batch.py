from django.db.models import Count, Q
from rest_framework import serializers

from api.models import Batch, Candidate, DuplicateCheck
from api.serializers.common import format_aadhaar_last4
from api.services import draft_expiry


SECTION_FIELDS = ['logical', 'quantitative', 'verbal', 'programming']


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
