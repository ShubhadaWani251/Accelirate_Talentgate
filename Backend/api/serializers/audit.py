"""Read-side shaping for the Audit Log screen.

The AuditLog table stores machine codes - action_type='invite_sent', entity_type='candidate'.
Those are the right thing to store (stable, filterable, never re-translated) but they are not
what an administrator should be asked to read. This module turns each row into the four columns
the screen shows: when, who, which area of the app, and what actually happened.

The mapping lives here rather than in the frontend on purpose: the same wording is needed by any
future export or report, and a second copy in JavaScript would drift from this one.
"""

from rest_framework import serializers

from api.models import AuditLog

# Which part of the product the action belongs to - the "Action Page" column. Keyed on
# entity_type, with a couple of action-specific overrides below where one entity is touched
# from two different screens.
_PAGE_BY_ENTITY = {
    'batch': 'Batches',
    'candidate': 'Candidates',
    'question': 'Question Bank',
    'user': 'User & Access Management',
    'invitation': 'Candidates',
}

# Authentication isn't a "page" in the nav, but it is where these actions happen, and grouping
# them under User & Access Management would wrongly imply an admin did something to an account.
_PAGE_BY_ACTION = {
    'login': 'Sign In',
    'login_failed': 'Sign In',
    'logout': 'Sign In',
    'password_change': 'Profile',
    'password_reset': 'Forgot Password',
}

# One sentence per (action_type, entity_type). Written in the past tense and from the reader's
# point of view - "Created a batch", not "batch.create". Unknown combinations fall back to a
# readable rendering of the raw codes rather than a blank cell, so a newly added action type
# shows up as something legible until it gets an entry here.
_DESCRIPTIONS = {
    ('create', 'batch'): 'Created a batch',
    ('update', 'batch'): 'Updated batch configuration',
    ('upload', 'batch'): 'Uploaded a candidate spreadsheet to a batch',
    ('finalize', 'batch'): 'Activated a batch (Draft to In Progress)',
    ('deactivate', 'batch'): 'Deactivated a batch',
    ('delete', 'batch'): 'Deleted a batch',
    ('delete_candidates', 'batch'): 'Removed candidates from a batch',
    ('update', 'candidate'): 'Edited a candidate record',
    ('invite_sent', 'candidate'): 'Sent an assessment invitation',
    ('notify_sent', 'candidate'): 'Sent a notification email',
    ('certification_sent', 'candidate'): 'Sent a certification course email',
    ('create', 'question'): 'Added a question to the question bank',
    ('update', 'question'): 'Edited a question',
    ('delete', 'question'): 'Deleted a question',
    ('bulk_upload', 'question'): 'Bulk-uploaded questions from a spreadsheet',
    ('create', 'user'): 'Created a user account',
    ('update', 'user'): 'Updated a user account',
    ('deactivate', 'user'): 'Deactivated a user account',
    ('delete', 'user'): 'Deleted a user account',
    ('login', 'user'): 'Signed in',
    ('login_failed', 'user'): 'Failed sign-in attempt',
    ('logout', 'user'): 'Signed out',
    ('password_change', 'user'): 'Changed their own password',
    ('password_reset', 'user'): 'Reset their password via OTP',
}

# Detail keys worth appending to the description, and how to phrase them. Everything not listed
# here is dropped rather than dumped: action_details is a free-form JSON blob, and rendering it
# wholesale would eventually leak a candidate's personal data onto this screen.
_DETAIL_PHRASES = (
    ('rows_created', 'rows'),
    ('selected_count', 'selected'),
    ('uploaded_count', 'uploaded'),
    ('created_count', 'created'),
    ('candidate_count', 'candidates'),
    ('batch_id', 'batch'),
    ('subject', 'subject'),
)


def describe_action(action_type, entity_type, details=None):
    """The human sentence for one audit row, with a short detail suffix where useful."""
    base = _DESCRIPTIONS.get((action_type, entity_type))
    if base is None:
        # Legible fallback: 'some_new_action' on 'batch' -> "Some new action (batch)".
        base = f"{(action_type or 'unknown').replace('_', ' ').capitalize()} ({entity_type})"

    if isinstance(details, dict):
        parts = []
        for key, label in _DETAIL_PHRASES:
            if key not in details:
                continue
            value = details[key]
            if value in (None, '', [], {}):
                continue
            if isinstance(value, (list, tuple, set)):
                value = len(value)
            text = str(value)
            # A long free-text value (an email subject) would blow out the column.
            if len(text) > 60:
                text = text[:57] + '...'
            parts.append(f'{label}: {text}')
        if parts:
            base = f"{base} ({', '.join(parts)})"
    return base


class AuditLogSerializer(serializers.ModelSerializer):
    """One row of the Audit Log table: date/time, user, action page, action description."""
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    user_role = serializers.SerializerMethodField()
    action_page = serializers.SerializerMethodField()
    action_description = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            'log_id', 'created_at', 'user_name', 'user_email', 'user_role',
            'action_page', 'action_description',
            # Raw codes kept alongside the prose so the screen can filter on them without
            # reverse-engineering the sentence.
            'action_type', 'entity_type', 'entity_id', 'ip_address',
        ]

    def get_user_name(self, log):
        # user is SET_NULL: a deleted account's history survives, and must still render.
        return log.user.full_name if log.user else 'Deleted user'

    def get_user_email(self, log):
        return log.user.email if log.user else None

    def get_user_role(self, log):
        if not log.user or not log.user.role_id:
            return None
        return log.user.role.role_name

    def get_action_page(self, log):
        return (_PAGE_BY_ACTION.get(log.action_type)
                or _PAGE_BY_ENTITY.get(log.entity_type)
                or (log.entity_type or 'Unknown').title())

    def get_action_description(self, log):
        return describe_action(log.action_type, log.entity_type, log.action_details)
