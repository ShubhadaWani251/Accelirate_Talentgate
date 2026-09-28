"""The certification email body is editable, and can be made the new default.

Its wording used to be a constant, so changing it meant a code change and a deploy - which is
not a reasonable way to keep a candidate-facing letter current over years. It is editable per
send now, and optionally saved as the wording every later send starts from.

The hazard editable copy introduces is str.format: an unknown name in braces raises KeyError and
a stray brace raises ValueError, either of which would surface MID-SEND, after some candidates
had been emailed and some had not. So a body is rendered against dummy values before anything
leaves, and these tests pin that.
"""
import pytest

from api.models import Candidate, Setting
from api.services.email_templates import (
    CERTIFICATION_TEMPLATE, certification_body_error, get_certification_template,
    render_certification_email, save_certification_template,
)

pytestmark = pytest.mark.django_db

URL = '/api/candidates/send-certification/'


@pytest.fixture
def sent_bodies(monkeypatch):
    """Captures what each candidate's email body renders to, synchronously.

    send_notification_emails is fire-and-forget on a background thread, so asserting against
    mailoutbox is a race - it passes or fails on timing, which is why nothing else in the suite
    asserts on this path. Replacing the sender runs the same per-candidate body_for callable
    inline, which is the part these tests are actually about.
    """
    captured = []

    def _fake(candidates, subject, body_for):
        captured.extend((subject, body_for(c)) for c in candidates)

    monkeypatch.setattr('api.views.candidates.send_notification_emails', _fake)
    return captured


@pytest.fixture
def emailable(ta_user, make_batch, make_candidate):
    candidate = make_candidate(make_batch(ta_user), ta_user)
    Candidate.objects.filter(pk=candidate.pk).update(email='cert.target@example.test')
    candidate.refresh_from_db()
    return candidate


class TestBodyValidation:
    def test_an_unknown_placeholder_is_refused_by_name(self):
        error = certification_body_error('Dear {name}, your {salary} is ready')

        assert 'salary' in error
        assert '{deadline}' in error  # tells them what IS available

    def test_a_stray_brace_is_refused(self):
        assert 'unbalanced' in certification_body_error('Dear {name}, 50% of { things')

    def test_an_empty_body_is_refused(self):
        assert certification_body_error('   ') == 'The email body cannot be empty.'

    def test_a_too_long_body_is_refused(self):
        assert 'too long' in certification_body_error('x' * 20001)

    @pytest.mark.parametrize('body', [
        'Dear {name}, deadline {deadline}',
        'Links: {course_1_url} and {course_2_url}',
        'A literal brace {{like this}} is fine',
        'No placeholders at all is fine too',
    ])
    def test_valid_bodies_pass(self, body):
        assert certification_body_error(body) is None

    def test_the_shipped_default_is_itself_valid(self):
        """Guards the built-in copy against an edit that breaks it for everyone."""
        assert certification_body_error(CERTIFICATION_TEMPLATE['body']) is None


class TestTheStoredTemplate:
    def test_it_falls_back_to_the_built_in_copy(self):
        """Nothing saved - every existing database - must behave exactly as before."""
        assert get_certification_template()['body'] == CERTIFICATION_TEMPLATE['body']

    def test_a_saved_body_wins(self, admin_user):
        save_certification_template('New subject', 'Dear {name}, new wording.', admin_user)

        template = get_certification_template()
        assert template['subject'] == 'New subject'
        assert template['body'] == 'Dear {name}, new wording.'

    def test_a_long_body_survives_the_round_trip(self, admin_user):
        """Setting.setting_value was CharField(255); the approved copy is ~1,200 characters, so
        storing it at all required widening that column.
        """
        long_body = 'Dear {name},\n\n' + ('Some approved paragraph. ' * 200)
        save_certification_template('S', long_body, admin_user)

        assert get_certification_template()['body'] == long_body

    def test_rendering_uses_the_saved_wording(self, admin_user, emailable):
        save_certification_template('S', 'Hi {name}, due {deadline}.', admin_user)

        _subject, body = render_certification_email(emailable, '5 March')

        assert body == f'Hi {emailable.full_name}, due 5 March.'


class TestSendingWithEditedWording:
    def _send(self, client, candidate, **extra):
        payload = {'candidate_ids': [candidate.candidate_id], 'deadline': '5 March 2026'}
        payload.update(extra)
        return client.post(URL, payload, format='json')

    def test_the_modal_can_read_the_current_wording(self, ta_user, client_for):
        response = client_for(ta_user).get(URL)

        assert response.status_code == 200
        assert response.data['body'] == CERTIFICATION_TEMPLATE['body']
        assert response.data['is_customised'] is False
        assert 'name' in response.data['placeholders']

    def test_an_edited_body_is_used_for_that_send(
        self, ta_user, client_for, emailable, sent_bodies,
    ):
        response = self._send(client_for(ta_user), emailable,
                              body='Dear {name}, please finish by {deadline}.')

        assert response.status_code == 200, response.data
        assert sent_bodies == [
            ('Certification Course Completion - Action Required',
             f'Dear {emailable.full_name}, please finish by 5 March 2026.'),
        ]

    def test_an_edit_is_not_saved_unless_asked(self, ta_user, client_for, emailable):
        self._send(client_for(ta_user), emailable, body='One-off wording for {name}.')

        assert get_certification_template()['body'] == CERTIFICATION_TEMPLATE['body']

    def test_save_as_default_makes_it_stick(self, ta_user, client_for, emailable):
        self._send(client_for(ta_user), emailable,
                   body='Dear {name}, new house style.', save_as_default=True)

        assert get_certification_template()['body'] == 'Dear {name}, new house style.'

    def test_a_broken_placeholder_is_refused_before_anything_is_sent(
        self, ta_user, client_for, emailable, sent_bodies,
    ):
        """The whole point of validating up front: a KeyError raised during the send loop would
        leave some candidates emailed and some not.
        """
        response = self._send(client_for(ta_user), emailable, body='Dear {nmae}, oops.')

        assert response.status_code == 400
        assert 'nmae' in response.data['detail']
        assert sent_bodies == []

    def test_a_broken_body_is_never_saved_as_the_default(
        self, ta_user, client_for, emailable,
    ):
        self._send(client_for(ta_user), emailable, body='Dear {nmae},', save_as_default=True)

        assert get_certification_template()['body'] == CERTIFICATION_TEMPLATE['body']
        assert not Setting.objects.filter(setting_key='email_templates.certification.body').exists()

    def test_omitting_the_body_still_sends_the_current_wording(
        self, ta_user, client_for, emailable, sent_bodies,
    ):
        """An older caller that passes only a deadline must keep working."""
        response = self._send(client_for(ta_user), emailable)

        assert response.status_code == 200, response.data
        assert 'Congratulations for clearing HR screening round' in sent_bodies[0][1]

    def test_an_empty_subject_is_refused(self, ta_user, client_for, emailable):
        response = self._send(client_for(ta_user), emailable, subject='   ')

        assert response.status_code == 400
        assert 'subject' in response.data['detail'].lower()
