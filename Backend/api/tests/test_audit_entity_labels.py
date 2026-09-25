"""Audit rows name the record they happened to.

Reported as "the same entry appears multiple times". They were not duplicates: sending one
batch's invitations writes one row per candidate, and the screen showed four columns - time,
user, page, description - none of which differ between them. 23 different candidates rendered
as the identical sentence 23 times at the same second, which reads as a logging fault.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from api.models import AuditLog, Candidate
from api.serializers.audit import describe_action
from api.views.audit import build_entity_labels

pytestmark = pytest.mark.django_db


def _log(user, candidate=None, **kwargs):
    params = dict(
        user=user, action_type='invite_sent', entity_type='candidate',
        entity_id=candidate.candidate_id if candidate else 0,
    )
    params.update(kwargs)
    return AuditLog.objects.create(**params)


class TestBuildEntityLabels:
    def test_candidates_are_named(self, ta_user, make_batch, make_candidate):
        batch = make_batch(ta_user)
        one = make_candidate(batch, ta_user)
        two = make_candidate(batch, ta_user)
        logs = [_log(ta_user, one), _log(ta_user, two)]

        labels = build_entity_labels(logs)

        assert labels[('candidate', one.candidate_id)] == one.full_name
        assert labels[('candidate', two.candidate_id)] == two.full_name

    def test_batches_and_users_are_named_too(self, ta_user, make_batch):
        batch = make_batch(ta_user)
        logs = [
            _log(ta_user, action_type='finalize', entity_type='batch', entity_id=batch.batch_id),
            _log(ta_user, action_type='login', entity_type='user', entity_id=ta_user.user_id),
        ]

        labels = build_entity_labels(logs)

        assert labels[('batch', batch.batch_id)] == batch.batch_name
        assert labels[('user', ta_user.user_id)] == ta_user.full_name

    def test_a_deleted_target_simply_has_no_label(self, ta_user):
        """The log is append-only and outlives what it refers to. A missing name means the
        record is gone, which is the honest answer - not a crash, and not a wrong name.
        """
        logs = [_log(ta_user, entity_type='candidate', entity_id=99999999)]

        assert build_entity_labels(logs) == {}

    def test_an_entity_type_with_no_specific_row_is_skipped(self, ta_user):
        """batch_defaults is one org-wide setting - there is no record to name."""
        logs = [_log(ta_user, action_type='update', entity_type='batch_defaults', entity_id=0)]

        assert build_entity_labels(logs) == {}

    def test_it_is_one_query_per_entity_type_not_per_row(
        self, ta_user, make_batch, make_candidate, django_assert_num_queries,
    ):
        """The whole reason this is built for the page rather than resolved per row."""
        batch = make_batch(ta_user)
        logs = [_log(ta_user, make_candidate(batch, ta_user)) for _ in range(10)]

        with django_assert_num_queries(1):
            build_entity_labels(logs)


class TestTheAuditScreenCanTellTheRowsApart:
    def test_each_invitation_row_carries_its_own_candidate(
        self, admin_user, ta_user, make_batch, make_candidate, client_for,
    ):
        batch = make_batch(ta_user)
        candidates = [make_candidate(batch, ta_user) for _ in range(3)]
        # Same second, same user, same action - exactly what sending a batch produces.
        stamp = timezone.now()
        for candidate in candidates:
            log = _log(ta_user, candidate)
            AuditLog.objects.filter(pk=log.pk).update(created_at=stamp)

        response = client_for(admin_user).get('/api/audit-logs/', {'action': 'invite_sent'})

        assert response.status_code == 200, response.data
        labels = [row['entity_label'] for row in response.data['results']]
        assert sorted(labels) == sorted(c.full_name for c in candidates)
        # The point of the fix: no two rows read the same any more.
        assert len(set(labels)) == len(labels)

    def test_rows_are_not_actually_duplicated_in_the_first_place(
        self, admin_user, ta_user, make_batch, make_candidate, client_for,
    ):
        """Guards the other half of the report: whatever the screen looked like, the API must
        not be returning one row twice.
        """
        batch = make_batch(ta_user)
        for _ in range(3):
            _log(ta_user, make_candidate(batch, ta_user))

        response = client_for(admin_user).get('/api/audit-logs/', {'action': 'invite_sent'})

        ids = [row['log_id'] for row in response.data['results']]
        assert len(ids) == len(set(ids))

    def test_a_row_with_no_resolvable_target_still_renders(
        self, admin_user, ta_user, client_for,
    ):
        _log(ta_user, entity_type='candidate', entity_id=99999999)

        response = client_for(admin_user).get('/api/audit-logs/', {'action': 'invite_sent'})

        assert response.status_code == 200
        assert response.data['results'][0]['entity_label'] is None


class TestExamSectionRowsReadAsEnglish:
    """Section and defaults rows fell through every mapping and rendered as raw database codes:
    the Action Page column read "Question_Section" - a column name, underscore and all - and the
    description read "Update (question_section)".
    """

    @pytest.mark.parametrize('action_type, expected', [
        ('create', 'Added an exam section'),
        ('deactivate', 'Deactivated an exam section'),
        ('restore', 'Restored an exam section'),
        ('delete', 'Deleted an exam section'),
        # Written before deactivate/restore had their own action types. The log is append-only,
        # so these rows exist and still have to read as something.
        ('update', 'Changed an exam section'),
    ])
    def test_each_section_action_has_a_sentence(self, action_type, expected):
        assert describe_action(action_type, 'question_section') == expected

    def test_the_defaults_screen_has_one_too(self):
        assert describe_action('update', 'batch_defaults') == (
            'Updated the default batch configuration')

    @pytest.mark.parametrize('entity_type, expected_page', [
        ('question_section', 'Question Bank'),
        ('batch_defaults', 'Batches'),
    ])
    def test_the_action_page_is_a_real_screen_name(
        self, admin_user, ta_user, client_for, entity_type, expected_page,
    ):
        AuditLog.objects.create(user=ta_user, action_type='update',
                                entity_type=entity_type, entity_id=0)

        response = client_for(admin_user).get('/api/audit-logs/', {'entity': entity_type})

        assert response.data['results'][0]['action_page'] == expected_page

    def test_no_row_renders_a_raw_entity_code(self, admin_user, ta_user, client_for):
        """The shape of the original complaint: an underscore in a user-facing cell means a
        database identifier reached the screen.
        """
        for entity_type in ('question_section', 'batch_defaults'):
            AuditLog.objects.create(user=ta_user, action_type='update',
                                    entity_type=entity_type, entity_id=0)

        response = client_for(admin_user).get('/api/audit-logs/')

        for row in response.data['results']:
            assert '_' not in row['action_page'], row
            assert '(' not in row['action_description'] or ':' in row['action_description'], row


class TestDeactivateAndRestoreAreToldApart:
    def test_deactivating_logs_its_own_action_type(
        self, admin_user, client_for, get_section,
    ):
        section = get_section('tellapart', 'Tell Apart')

        client_for(admin_user).delete('/api/questions/sections/%d/' % section.section_id)

        row = AuditLog.objects.filter(entity_type='question_section').latest('log_id')
        assert row.action_type == 'deactivate'
        assert describe_action(row.action_type, row.entity_type) == 'Deactivated an exam section'

    def test_restoring_logs_a_different_one(self, admin_user, client_for, get_section):
        """Both used to log 'update', so the two opposite halves of the feature produced
        identical audit rows - the exact problem this screen exists to avoid.
        """
        section = get_section('tellapart2', 'Tell Apart Two')
        client = client_for(admin_user)
        client.delete('/api/questions/sections/%d/' % section.section_id)

        client.patch('/api/questions/sections/%d/' % section.section_id,
                     {'is_active': True}, format='json')

        row = AuditLog.objects.filter(entity_type='question_section').latest('log_id')
        assert row.action_type == 'restore'
        assert describe_action(row.action_type, row.entity_type) == 'Restored an exam section'
