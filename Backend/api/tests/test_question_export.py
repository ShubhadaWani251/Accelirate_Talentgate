"""api.views.integrations.ActiveQuestionExportView - the service-to-service question export.

Covers exactly the properties that matter for a key-authenticated, non-staff endpoint: no key
means no data, the wrong key means no data, the right key returns only Active questions (with
answers), and every successful call is written to AuditLog for an admin to see.
"""
import pytest

from api.models import AuditLog, Question, QuestionBankSection

pytestmark = pytest.mark.django_db


@pytest.fixture
def section():
    return QuestionBankSection.objects.create(
        section_name='Logical & Analytical Reasoning', section_key='logical',
    )


@pytest.fixture
def make_question(section):
    counter = {'n': 0}

    def _make(status=Question.Status.ACTIVE):
        counter['n'] += 1
        return Question.objects.create(
            question_code=f'Q-{counter["n"]:04d}',
            section=section,
            question_text=f'Sample question {counter["n"]}?',
            option_a='A', option_b='B', option_c='C', option_d='D',
            correct_option='A',
            difficulty=Question.Difficulty.EASY,
            status=status,
        )
    return _make


class TestActiveQuestionExportAuth:
    URL = '/api/integrations/questions/active/'

    def test_missing_api_key_is_rejected(self, api_client, make_question):
        make_question()
        response = api_client.get(self.URL)
        assert response.status_code == 401

    def test_wrong_api_key_is_rejected(self, api_client, make_question):
        make_question()
        response = api_client.get(self.URL, HTTP_X_API_KEY='not-the-real-key')
        assert response.status_code == 401

    def test_correct_api_key_is_accepted(self, api_client, make_question, settings):
        make_question()
        response = api_client.get(self.URL, HTTP_X_API_KEY=settings.QUESTION_EXPORT_API_KEY)
        assert response.status_code == 200

    def test_blank_configured_key_refuses_every_request(self, api_client, make_question, settings):
        # The unprovisioned state (QUESTION_EXPORT_API_KEY='') must fail closed, not compare
        # an empty header against an empty setting and let it through.
        settings.QUESTION_EXPORT_API_KEY = ''
        make_question()
        response = api_client.get(self.URL, HTTP_X_API_KEY='')
        assert response.status_code == 401


class TestActiveQuestionExportContent:
    URL = '/api/integrations/questions/active/'

    def test_only_active_questions_are_returned(self, api_client, make_question, settings):
        active = make_question(status=Question.Status.ACTIVE)
        make_question(status=Question.Status.INACTIVE)

        response = api_client.get(self.URL, HTTP_X_API_KEY=settings.QUESTION_EXPORT_API_KEY)

        codes = [row['question_code'] for row in response.data]
        assert codes == [active.question_code]

    def test_correct_option_is_included(self, api_client, make_question, settings):
        make_question()
        response = api_client.get(self.URL, HTTP_X_API_KEY=settings.QUESTION_EXPORT_API_KEY)
        assert response.data[0]['correct_option'] == 'A'

    def test_a_successful_export_is_written_to_the_audit_log(
        self, api_client, make_question, settings
    ):
        make_question()
        before = AuditLog.objects.count()

        api_client.get(self.URL, HTTP_X_API_KEY=settings.QUESTION_EXPORT_API_KEY)

        assert AuditLog.objects.count() == before + 1
        log = AuditLog.objects.latest('log_id')
        assert log.action_type == 'service_export'
        assert log.entity_type == 'question'
        assert log.requires_review is True
        assert log.user is None
