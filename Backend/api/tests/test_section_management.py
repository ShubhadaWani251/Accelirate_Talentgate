"""Adding, deleting and retiring exam sections from Question Bank Management.

Sections are data now (see migration 0035), so an Admin can add one and every screen picks it
up. Deleting is the half that needs care: Question, BatchSection and AttemptSectionScore all
reference a section with PROTECT, so a delete that went through would either take the question
bank's content with it or erase what a cohort was actually assessed on. It is therefore allowed
only while nothing depends on the section, and refused with the counts otherwise - retiring
(is_active=False) being the safe alternative that leaves existing results alone.
"""
import pytest

from api.models import Batch, BatchSection, Question, QuestionBankSection, Setting

pytestmark = pytest.mark.django_db


def _url(section):
    return '/api/questions/sections/%d/' % section.section_id


@pytest.fixture
def unused_section(db):
    return QuestionBankSection.objects.create(
        section_name='Data Interpretation', section_key='data_interp', display_order=50,
    )


class TestAddingASection:
    def test_the_key_is_derived_from_the_name(self, admin_user, client_for):
        response = client_for(admin_user).post('/api/questions/sections/', {
            'section_name': 'Data Interpretation',
        }, format='json')

        assert response.status_code == 201, response.data
        # Not asked for on the form: this key becomes a query-param name and a dict key in the
        # per-section score map, so it is derived rather than typed.
        assert response.data['section_key'] == 'data_interpretation'

    def test_two_names_reducing_to_the_same_key_both_work(self, admin_user, client_for):
        client = client_for(admin_user)
        client.post('/api/questions/sections/', {'section_name': 'Data Interpretation'},
                    format='json')
        response = client.post('/api/questions/sections/',
                               {'section_name': 'Data-Interpretation'}, format='json')

        # section_key is unique, so without the suffixing this would be an integrity error.
        assert response.status_code == 201, response.data
        assert response.data['section_key'] == 'data_interpretation_2'

    def test_a_duplicate_name_is_refused(self, admin_user, client_for, unused_section):
        response = client_for(admin_user).post('/api/questions/sections/', {
            'section_name': 'data interpretation',
        }, format='json')

        assert response.status_code == 400
        assert 'already exists' in str(response.data)

    def test_a_name_with_no_letters_or_digits_is_refused(self, admin_user, client_for):
        response = client_for(admin_user).post('/api/questions/sections/',
                                                {'section_name': '---'}, format='json')

        # It would derive an empty key, which nothing downstream could address.
        assert response.status_code == 400

    def test_a_ta_cannot_add_a_section(self, ta_user, client_for):
        response = client_for(ta_user).post('/api/questions/sections/',
                                             {'section_name': 'Sneaky'}, format='json')
        assert response.status_code == 403

    def test_a_ta_can_still_read_the_list(self, ta_user, client_for, unused_section):
        # A TA needs it for All Candidates' score columns - without it that table has no headers.
        assert client_for(ta_user).get('/api/questions/sections/').status_code == 200


class TestDeletingASection:
    def test_an_unused_section_is_removed_outright(
        self, admin_user, client_for, unused_section,
    ):
        response = client_for(admin_user).delete(_url(unused_section))

        assert response.status_code == 200, response.data
        # Nothing depended on it, so there is no past to preserve and no tombstone left behind.
        assert response.data['removed'] is True
        assert not QuestionBankSection.objects.filter(pk=unused_section.pk).exists()

    def test_its_default_settings_go_with_it(self, admin_user, client_for, unused_section):
        Setting.objects.create(setting_key='exam_config.section.data_interp.questions',
                               setting_value='10', setting_group='exam_config')

        client_for(admin_user).delete(_url(unused_section))

        # Left behind, these would sit in the Setting table forever and silently reapply to a
        # later section that happened to derive the same key.
        assert not Setting.objects.filter(
            setting_key__startswith='exam_config.section.data_interp.').exists()

    def test_a_section_holding_questions_is_kept_but_retired(
        self, admin_user, client_for, unused_section,
    ):
        Question.objects.create(
            question_code='Q-DI-1', section=unused_section, question_text='q',
            option_a='a', option_b='b', correct_option='A',
            difficulty=Question.Difficulty.EASY,
        )

        response = client_for(admin_user).delete(_url(unused_section))

        assert response.status_code == 200, response.data
        assert response.data['removed'] is False
        # The questions are not destroyed - they stay in the bank and remain manageable.
        assert Question.objects.filter(section=unused_section).count() == 1
        unused_section.refresh_from_db()
        assert unused_section.is_active is False

    def test_a_section_a_batch_has_used_is_kept_but_retired(
        self, admin_user, ta_user, client_for, make_batch, unused_section,
    ):
        batch = make_batch(ta_user, status=Batch.Status.IN_PROGRESS)
        BatchSection.objects.create(batch=batch, section=unused_section,
                                    question_count=10, cutoff=70)

        response = client_for(admin_user).delete(_url(unused_section))

        assert response.status_code == 200, response.data
        assert response.data['removed'] is False
        assert response.data['batch_count'] == 1
        # The one that really matters: that batch's candidates were assessed on this section,
        # and their results have to keep describing the exam they actually sat.
        assert batch.sections.filter(section=unused_section).exists()
        assert QuestionBankSection.objects.filter(pk=unused_section.pk).exists()

    def test_a_deleted_section_leaves_new_batches(
        self, admin_user, ta_user, client_for, make_batch, unused_section, get_section,
    ):
        get_section('logical')  # something has to survive, or no batch can be created
        BatchSection.objects.create(batch=make_batch(ta_user), section=unused_section,
                                    question_count=10, cutoff=70)

        client_for(admin_user).delete(_url(unused_section))

        created = client_for(ta_user).post(
            '/api/batches/', {'batch_name': 'After Delete', 'college_name': 'C'}, format='json',
        )
        assert 'data_interp' not in [s['section_key'] for s in created.data['sections']]

    def test_a_deleted_section_also_leaves_draft_batches(
        self, admin_user, ta_user, client_for, unused_section, get_section,
    ):
        """A draft has had nothing sent to its candidates, so it tracks what the org currently
        runs - leaving a deleted section on it would show a batch running something that exists
        nowhere else.
        """
        get_section('logical')
        created = client_for(ta_user).post(
            '/api/batches/', {'batch_name': 'Draft Before Delete', 'college_name': 'C'},
            format='json',
        ).data
        assert 'data_interp' in [s['section_key'] for s in created['sections']]

        client_for(admin_user).delete(_url(unused_section))

        refetched = client_for(ta_user).get('/api/batches/%d/' % created['batch_id']).data
        assert [s['section_key'] for s in refetched['sections']] == ['logical']

    def test_a_ta_cannot_delete_a_section(self, ta_user, client_for, unused_section):
        assert client_for(ta_user).delete(_url(unused_section)).status_code == 403
        assert QuestionBankSection.objects.filter(pk=unused_section.pk).exists()


class TestRetiringASection:
    def test_retiring_keeps_it_out_of_new_batches(
        self, admin_user, ta_user, client_for, unused_section, get_section,
    ):
        # Another section has to survive the retirement, or the batch cannot be created at all -
        # which is its own correct behaviour, but not what this test is about.
        get_section('logical')

        response = client_for(admin_user).patch(_url(unused_section), {'is_active': False},
                                                 format='json')
        assert response.status_code == 200, response.data
        assert response.data['is_active'] is False

        created = client_for(ta_user).post(
            '/api/batches/', {'batch_name': 'After Retiring', 'college_name': 'C'},
            format='json',
        )
        keys = [s['section_key'] for s in created.data['sections']]
        assert 'data_interp' not in keys

    def test_retiring_leaves_an_existing_batch_alone(
        self, admin_user, ta_user, client_for, make_batch, unused_section,
    ):
        batch = make_batch(ta_user, status=Batch.Status.IN_PROGRESS)
        BatchSection.objects.create(batch=batch, section=unused_section,
                                    question_count=10, cutoff=70)

        client_for(admin_user).patch(_url(unused_section), {'is_active': False}, format='json')

        # The whole point of retiring rather than deleting.
        assert batch.sections.filter(section=unused_section).exists()

    def test_a_retired_section_can_be_restored(self, admin_user, client_for, unused_section):
        client = client_for(admin_user)
        client.patch(_url(unused_section), {'is_active': False}, format='json')
        response = client.patch(_url(unused_section), {'is_active': True}, format='json')

        assert response.data['is_active'] is True

    def test_a_non_boolean_is_refused(self, admin_user, client_for, unused_section):
        response = client_for(admin_user).patch(_url(unused_section), {'is_active': 'yes'},
                                                 format='json')
        assert response.status_code == 400

    def test_in_use_is_reported_so_the_ui_can_explain_itself(
        self, admin_user, ta_user, client_for, make_batch, unused_section,
    ):
        rows = client_for(admin_user).get('/api/questions/sections/').data
        assert next(r for r in rows if r['section_key'] == 'data_interp')['in_use'] is False

        BatchSection.objects.create(batch=make_batch(ta_user), section=unused_section,
                                    question_count=10, cutoff=70)

        rows = client_for(admin_user).get('/api/questions/sections/').data
        assert next(r for r in rows if r['section_key'] == 'data_interp')['in_use'] is True


class TestARetiredSectionIsNotOfferedForNewWork:
    """Retiring keeps a section's history readable but must stop it soliciting NEW work.

    batch_defaults already left retired sections out of new batches. Two other surfaces did not,
    and both invited effort that could never be used: the question template still shipped a sheet
    to file fresh questions into, and the dashboard still reported the section as short of its
    minimum - an alarm about a shortfall nobody could act on usefully.
    """

    def _retire(self, section):
        QuestionBankSection.objects.filter(pk=section.pk).update(is_active=False)

    def test_the_question_template_has_no_sheet_for_a_retired_section(self, get_section):
        from api.services import question_bank

        live = get_section('still_live', 'Still Live')
        retired = get_section('gone', 'Gone')
        self._retire(retired)

        workbook = question_bank.generate_question_template_workbook()

        assert live.section_name in workbook.sheetnames
        assert retired.section_name not in workbook.sheetnames

    def test_an_upload_naming_a_retired_section_still_parses(self, get_section):
        """Asymmetric on purpose: the template stops OFFERING the sheet, but a file prepared
        before the section was retired must not start failing on a sheet name this app itself
        handed out.
        """
        from api.services import question_bank

        self._retire(get_section('gone_too', 'Gone Too'))

        sections_by_key = question_bank._validation_context()[0]

        assert 'gone_too' in sections_by_key
        assert 'gone too' in sections_by_key

    def test_dashboard_health_ignores_a_retired_section(self, get_section):
        from api.serializers.dashboard import _build_question_bank_health

        live = get_section('health_live', 'Health Live')
        retired = get_section('health_gone', 'Health Gone')
        self._retire(retired)

        names = {row['section_name'] for row in _build_question_bank_health()}

        assert live.section_name in names
        assert retired.section_name not in names
