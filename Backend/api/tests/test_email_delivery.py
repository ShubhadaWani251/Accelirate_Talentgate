"""Invitation email: delivery status, failure reporting, the retry sweep, and the HTML body.

The governing rule is that the UI must never show an email as sent when the provider reported a
failure, and must never leave a failure without a reason attached - "unverified sender",
"invalid address" and "timeout" need three different fixes and only the message distinguishes
them.
"""

from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from api.models import Batch, Invitation
from api.services import invites
from api.services.email_templates import text_body_to_html


class TestErrorSummary:
    def test_the_providers_own_message_is_extracted(self):
        exc = RuntimeError(
            'SendGrid API response 403 (Forbidden):\n'
            '  "message": "The from address does not match a verified Sender Identity."'
        )
        summary = invites.summarize_send_error(exc)
        assert 'does not match a verified Sender Identity' in summary

    def test_the_exception_class_is_named(self):
        assert invites.summarize_send_error(ValueError('bad')).startswith('ValueError:')

    def test_a_huge_error_is_truncated(self):
        """This value is rendered in a table cell; the full traceback is in the log."""
        assert len(invites.summarize_send_error(RuntimeError('x' * 5000))) <= 320

    def test_the_raw_response_body_is_not_dumped_wholesale(self):
        """Provider errors echo the request back, which can include the Authorization header.
        This value is served to the browser, so it must not carry credentials.
        """
        exc = RuntimeError(
            'Sending failed\n'
            'Request: POST /v3/mail/send\n'
            'Headers: {"Authorization": "Bearer SG.SECRETKEYVALUE12345"}\n'
            '  "message": "Bad Request"'
        )
        summary = invites.summarize_send_error(exc)
        assert 'SG.SECRETKEYVALUE12345' not in summary
        assert 'Authorization' not in summary


class TestSendRecordsStatus:
    def test_a_successful_send_is_recorded_as_sent(self, ta_user, make_batch, make_candidate,
                                                   make_invitation):
        invitation = make_invitation(make_candidate(make_batch(ta_user), ta_user), ta_user)

        assert invites.send_invite_and_record(invitation, 'https://exam.example.test') is True

        invitation.refresh_from_db()
        assert invitation.email_status == Invitation.EmailStatus.SENT
        assert invitation.email_sent_at is not None
        assert invitation.email_last_attempt_at is not None
        assert invitation.email_error is None
        assert len(mail.outbox) == 1

    def test_a_failed_send_is_recorded_as_failed_with_a_reason(
        self, ta_user, make_batch, make_candidate, make_invitation, monkeypatch
    ):
        invitation = make_invitation(make_candidate(make_batch(ta_user), ta_user), ta_user)

        def boom(*args, **kwargs):
            raise RuntimeError('"message": "Mailbox unavailable"')

        monkeypatch.setattr(invites, 'send_invite_email', boom)

        assert invites.send_invite_and_record(invitation, 'https://exam.example.test') is False

        invitation.refresh_from_db()
        assert invitation.email_status == Invitation.EmailStatus.FAILED
        assert 'Mailbox unavailable' in invitation.email_error
        # Never claim a send time for something that did not send.
        assert invitation.email_sent_at is None
        # But do record that an attempt happened, or a repeatedly-failing row looks untried.
        assert invitation.email_last_attempt_at is not None

    def test_a_later_success_clears_the_earlier_reason(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        """A stale error sitting next to a SENT status reads as a current problem."""
        invitation = make_invitation(
            make_candidate(make_batch(ta_user), ta_user), ta_user,
            email_status=Invitation.EmailStatus.FAILED,
            email_error='RuntimeError: earlier failure',
        )

        invites.send_invite_and_record(invitation, 'https://exam.example.test')

        invitation.refresh_from_db()
        assert invitation.email_status == Invitation.EmailStatus.SENT
        assert invitation.email_error is None

    def test_one_bad_address_does_not_abandon_the_rest(
        self, ta_user, make_batch, make_candidate, make_invitation, monkeypatch
    ):
        """Previously an unexpected exception escaped the loop and every remaining invitation
        was left QUEUED forever, reading as still in flight.
        """
        batch = make_batch(ta_user)
        invitations = [make_invitation(make_candidate(batch, ta_user), ta_user)
                       for _ in range(3)]
        real_send = invites.send_invite_email
        calls = {'n': 0}

        def sometimes_fails(invitation, base_url):
            calls['n'] += 1
            if calls['n'] == 2:
                raise KeyError('a rendering bug, not a provider error')
            return real_send(invitation, base_url)

        monkeypatch.setattr(invites, 'send_invite_email', sometimes_fails)

        results = [invites.send_invite_and_record(i, 'https://exam.example.test')
                   for i in invitations]

        assert results == [True, False, True]
        statuses = [Invitation.objects.get(pk=i.pk).email_status for i in invitations]
        assert statuses == ['sent', 'failed', 'sent']
        # Nothing is left QUEUED - every row got a verdict.
        assert 'queued' not in statuses


class TestStatusShownByTheApi:
    def test_a_fresh_invitation_reports_queued_with_no_error(
        self, ta_user, client_for, make_batch, make_candidate, make_invitation
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user)
        make_invitation(candidate, ta_user)

        data = client_for(ta_user).get('/api/candidates/%d/' % candidate.candidate_id).data
        assert data['email_status'] == 'queued'
        assert data['email_error'] is None

    def test_the_newest_invitation_decides_the_reported_status(
        self, ta_user, client_for, make_batch, make_candidate, make_invitation
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user)
        make_invitation(candidate, ta_user,
                        email_status=Invitation.EmailStatus.FAILED,
                        email_error='RuntimeError: old failure')
        make_invitation(candidate, ta_user,
                        email_status=Invitation.EmailStatus.SENT,
                        email_sent_at=timezone.now())

        data = client_for(ta_user).get('/api/candidates/%d/' % candidate.candidate_id).data
        assert data['email_status'] == 'sent'
        assert not data['email_error']

    def test_a_newer_failure_is_not_masked_by_an_older_success(
        self, ta_user, client_for, make_batch, make_candidate, make_invitation
    ):
        """The direction that actually matters: a resend that failed must not read as sent
        because an earlier attempt succeeded.
        """
        candidate = make_candidate(make_batch(ta_user), ta_user)
        make_invitation(candidate, ta_user,
                        email_status=Invitation.EmailStatus.SENT,
                        email_sent_at=timezone.now())
        make_invitation(candidate, ta_user, is_re_invite=True,
                        email_status=Invitation.EmailStatus.FAILED,
                        email_error='RuntimeError: later failure')

        data = client_for(ta_user).get('/api/candidates/%d/' % candidate.candidate_id).data
        assert data['email_status'] == 'failed'
        assert data['email_error'] == 'RuntimeError: later failure'

    def test_email_status_is_separate_from_pipeline_status(
        self, ta_user, client_for, make_batch, make_candidate, make_invitation
    ):
        """A candidate can be 'Invited' while the invitation email failed - which is exactly why
        these are two columns and not one.
        """
        from api.models import Candidate
        candidate = make_candidate(make_batch(ta_user), ta_user,
                                   status=Candidate.Status.INVITED)
        make_invitation(candidate, ta_user, email_status=Invitation.EmailStatus.FAILED,
                        email_error='RuntimeError: nope')

        data = client_for(ta_user).get('/api/candidates/%d/' % candidate.candidate_id).data
        assert data['status'] == 'invited'
        assert data['email_status'] == 'failed'


class TestRetrySweep:
    """The command that covers a send interrupted by a deploy killing the worker thread."""

    def _stalled(self, make_invitation, candidate, user):
        return make_invitation(candidate, user, created_at=timezone.now() - timedelta(hours=2))

    def test_a_stalled_queued_invitation_is_resent(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user)
        invitation = self._stalled(make_invitation, candidate, ta_user)

        call_command('retry_stalled_invite_emails')

        invitation.refresh_from_db()
        assert invitation.email_status == Invitation.EmailStatus.SENT
        assert len(mail.outbox) == 1

    def test_a_freshly_queued_invitation_is_left_alone(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        """It is probably still in flight on a live thread; re-sending would double-deliver."""
        candidate = make_candidate(make_batch(ta_user), ta_user)
        invitation = make_invitation(candidate, ta_user)

        call_command('retry_stalled_invite_emails')

        invitation.refresh_from_db()
        assert invitation.email_status == Invitation.EmailStatus.QUEUED
        assert mail.outbox == []

    def test_dry_run_sends_nothing(self, ta_user, make_batch, make_candidate, make_invitation):
        candidate = make_candidate(make_batch(ta_user), ta_user)
        invitation = self._stalled(make_invitation, candidate, ta_user)

        call_command('retry_stalled_invite_emails', '--dry-run')

        invitation.refresh_from_db()
        assert invitation.email_status == Invitation.EmailStatus.QUEUED
        assert mail.outbox == []

    def test_failed_rows_are_skipped_by_default(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        """Most failure reasons are permanent; retrying them on a timer never fixes anything."""
        candidate = make_candidate(make_batch(ta_user), ta_user)
        self._stalled(make_invitation, candidate, ta_user).__class__.objects.filter(
            candidate=candidate).update(email_status=Invitation.EmailStatus.FAILED)

        call_command('retry_stalled_invite_emails')
        assert mail.outbox == []

    def test_failed_rows_are_retried_when_asked(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user)
        self._stalled(make_invitation, candidate, ta_user)
        Invitation.objects.filter(candidate=candidate).update(
            email_status=Invitation.EmailStatus.FAILED)

        call_command('retry_stalled_invite_emails', '--include-failed')
        assert len(mail.outbox) == 1

    def test_an_already_opened_link_is_not_resent(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        """It plainly arrived; the status is just stale."""
        candidate = make_candidate(make_batch(ta_user), ta_user)
        make_invitation(candidate, ta_user,
                        created_at=timezone.now() - timedelta(hours=2),
                        link_clicked_at=timezone.now())

        call_command('retry_stalled_invite_emails')
        assert mail.outbox == []

    def test_an_expired_link_is_not_resent(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        """Re-sending would email the candidate something that cannot be opened."""
        candidate = make_candidate(make_batch(ta_user), ta_user)
        make_invitation(candidate, ta_user,
                        created_at=timezone.now() - timedelta(hours=2),
                        link_expired_at=timezone.now() - timedelta(minutes=1))

        call_command('retry_stalled_invite_emails')
        assert mail.outbox == []

    @pytest.mark.parametrize('status', [Batch.Status.DRAFT, Batch.Status.CANCELLED])
    def test_batches_that_may_not_invite_are_skipped(
        self, ta_user, make_batch, make_candidate, make_invitation, status
    ):
        """A cancelled batch must not email a fresh assessment link, and a Draft has not been
        activated yet. The sweep must not become a way around that rule.
        """
        candidate = make_candidate(make_batch(ta_user, status=status), ta_user)
        make_invitation(candidate, ta_user, created_at=timezone.now() - timedelta(hours=2))

        call_command('retry_stalled_invite_emails')
        assert mail.outbox == []

    def test_a_candidate_with_no_address_is_skipped(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user, email='')
        make_invitation(candidate, ta_user, created_at=timezone.now() - timedelta(hours=2))

        call_command('retry_stalled_invite_emails')
        assert mail.outbox == []

    def test_the_run_is_bounded(self, ta_user, make_batch, make_candidate, make_invitation):
        batch = make_batch(ta_user)
        for _ in range(5):
            make_invitation(make_candidate(batch, ta_user), ta_user,
                            created_at=timezone.now() - timedelta(hours=2))

        call_command('retry_stalled_invite_emails', '--max', '2')
        assert len(mail.outbox) == 2


class TestInvitationEmailBody:
    def test_the_email_is_multipart_with_html_last(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        """Clients pick the LAST acceptable part of a multipart/alternative, so the HTML - the
        one with the clickable button - has to come after the plain text.
        """
        invitation = make_invitation(make_candidate(make_batch(ta_user), ta_user), ta_user)
        invites.send_invite_and_record(invitation, 'https://exam.example.test')

        message = mail.outbox[0]
        assert message.alternatives, 'no HTML alternative attached'
        assert message.alternatives[0][1] == 'text/html'
        assert 'exam.example.test' in message.body

    def test_the_link_is_a_real_anchor_in_the_html(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        invitation = make_invitation(make_candidate(make_batch(ta_user), ta_user), ta_user)
        invites.send_invite_and_record(invitation, 'https://exam.example.test')

        html = mail.outbox[0].alternatives[0][0]
        assert 'https://exam.example.test/t/%s' % invitation.unique_link_token in html
        assert '<a href=' in html

    def test_the_bare_url_survives_in_the_plain_text_part(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        """So a text-only client, or a button stripped by a mail gateway, still leaves the
        candidate something they can copy.
        """
        invitation = make_invitation(make_candidate(make_batch(ta_user), ta_user), ta_user)
        invites.send_invite_and_record(invitation, 'https://exam.example.test')

        assert invitation.unique_link_token in mail.outbox[0].body


class TestCtaButtonRendersInOutlook:
    """Outlook renders HTML with Word, which ignores much of what a browser accepts."""

    URL = 'https://exam.example.test/t/TOKEN123'

    def html(self):
        return text_body_to_html('Assessment Link:\n%s\n\nRegards' % self.URL,
                                 cta_url=self.URL)

    def test_the_button_is_a_table(self):
        """Word does not honour display:inline-block, so a styled anchor collapses."""
        assert 'role="presentation"' in self.html()

    def test_padding_is_on_the_cell_not_the_anchor(self):
        html = self.html()
        assert 'padding:14px 32px' in html
        assert 'inline-block' not in html

    def test_mso_padding_alt_is_present(self):
        assert 'mso-padding-alt' in self.html()

    def test_the_anchor_sets_its_own_colour(self):
        """Gmail recolours unstyled links, which on a dark button means invisible text."""
        assert 'color:#ffffff' in self.html()

    def test_it_opens_in_a_browser(self):
        assert 'target="_blank"' in self.html()

    def test_there_is_no_style_block(self):
        """Gmail strips <style>, so anything defined there is lost."""
        assert '<style' not in self.html()

    def test_no_button_is_rendered_without_a_cta(self):
        assert 'role="presentation"' not in text_body_to_html('no link in this body')
