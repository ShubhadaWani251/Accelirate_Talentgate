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


class TestRetryCountInTheDisplayLabel:
    """retry_count changes what a FAILED or SENT row actually means (still eligible for another
    automatic attempt, given up on, or only sent because the sweep stepped in) - the raw
    EmailStatus choice alone ('Failed', 'Sent') does not say any of that.
    """

    def test_a_fresh_failure_reads_as_retry_pending(
        self, ta_user, client_for, make_batch, make_candidate, make_invitation
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user)
        make_invitation(candidate, ta_user, email_status=Invitation.EmailStatus.FAILED,
                        email_error='RuntimeError: transient')

        data = client_for(ta_user).get('/api/candidates/%d/' % candidate.candidate_id).data
        assert data['email_retry_count'] == 0
        assert 'retry pending' in data['email_status_display'].lower()

    def test_a_failure_at_the_retry_limit_reads_as_exhausted(
        self, ta_user, client_for, make_batch, make_candidate, make_invitation, settings
    ):
        settings.INVITE_MAX_RETRY_ATTEMPTS = 3
        candidate = make_candidate(make_batch(ta_user), ta_user)
        invitation = make_invitation(candidate, ta_user,
                                     email_status=Invitation.EmailStatus.FAILED,
                                     email_error='RuntimeError: permanent')
        Invitation.objects.filter(pk=invitation.pk).update(retry_count=3)

        data = client_for(ta_user).get('/api/candidates/%d/' % candidate.candidate_id).data
        assert data['email_retry_count'] == 3
        assert 'exhausted' in data['email_status_display'].lower()

    def test_a_first_try_success_has_no_retry_wording(
        self, ta_user, client_for, make_batch, make_candidate, make_invitation
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user)
        make_invitation(candidate, ta_user, email_status=Invitation.EmailStatus.SENT,
                        email_sent_at=timezone.now())

        data = client_for(ta_user).get('/api/candidates/%d/' % candidate.candidate_id).data
        assert data['email_status_display'] == 'Sent'

    def test_a_success_after_retries_says_so(
        self, ta_user, client_for, make_batch, make_candidate, make_invitation
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user)
        invitation = make_invitation(candidate, ta_user,
                                     email_status=Invitation.EmailStatus.SENT,
                                     email_sent_at=timezone.now())
        Invitation.objects.filter(pk=invitation.pk).update(retry_count=2)

        data = client_for(ta_user).get('/api/candidates/%d/' % candidate.candidate_id).data
        assert data['email_retry_count'] == 2
        assert '2 retries' in data['email_status_display']


class TestProcessEmailQueue:
    """The ONLY thing that actually sends an invitation email - creating an Invitation just
    queues it. See the command's own module docstring for why this replaced the old
    background-thread-plus-safety-net-sweep shape.
    """

    def test_a_queued_invitation_is_sent(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user)
        invitation = make_invitation(candidate, ta_user)

        call_command('process_email_queue')

        invitation.refresh_from_db()
        assert invitation.email_status == Invitation.EmailStatus.SENT
        assert len(mail.outbox) == 1

    def test_dry_run_sends_nothing(self, ta_user, make_batch, make_candidate, make_invitation):
        candidate = make_candidate(make_batch(ta_user), ta_user)
        invitation = make_invitation(candidate, ta_user)

        call_command('process_email_queue', '--dry-run')

        invitation.refresh_from_db()
        assert invitation.email_status == Invitation.EmailStatus.QUEUED
        assert mail.outbox == []

    def test_failed_rows_are_skipped_by_default(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        """Most failure reasons are permanent; retrying them on a timer never fixes anything."""
        candidate = make_candidate(make_batch(ta_user), ta_user)
        make_invitation(candidate, ta_user, email_status=Invitation.EmailStatus.FAILED)

        call_command('process_email_queue')
        assert mail.outbox == []

    def test_failed_rows_are_retried_when_asked(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user)
        make_invitation(candidate, ta_user, email_status=Invitation.EmailStatus.FAILED)

        call_command('process_email_queue', '--include-failed')
        assert len(mail.outbox) == 1

    def test_an_already_opened_link_is_not_resent(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        """It plainly arrived; the status is just stale."""
        candidate = make_candidate(make_batch(ta_user), ta_user)
        make_invitation(candidate, ta_user,
                        email_status=Invitation.EmailStatus.FAILED,
                        link_clicked_at=timezone.now())

        call_command('process_email_queue', '--include-failed')
        assert mail.outbox == []

    def test_an_expired_link_is_not_sent(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        """Sending it would email the candidate something that cannot be opened."""
        candidate = make_candidate(make_batch(ta_user), ta_user)
        make_invitation(candidate, ta_user,
                        link_expired_at=timezone.now() - timedelta(minutes=1))

        call_command('process_email_queue')
        assert mail.outbox == []

    @pytest.mark.parametrize('status', [Batch.Status.DRAFT, Batch.Status.CANCELLED])
    def test_batches_that_may_not_invite_are_skipped(
        self, ta_user, make_batch, make_candidate, make_invitation, status
    ):
        """A cancelled batch must not email a fresh assessment link, and a Draft has not been
        activated yet. The worker must not become a way around that rule.
        """
        candidate = make_candidate(make_batch(ta_user, status=status), ta_user)
        make_invitation(candidate, ta_user)

        call_command('process_email_queue')
        assert mail.outbox == []

    def test_a_candidate_with_no_address_is_skipped(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user, email='')
        make_invitation(candidate, ta_user)

        call_command('process_email_queue')
        assert mail.outbox == []

    def test_the_run_is_bounded(self, ta_user, make_batch, make_candidate, make_invitation):
        batch = make_batch(ta_user)
        for _ in range(5):
            make_invitation(make_candidate(batch, ta_user), ta_user)

        call_command('process_email_queue', '--max', '2')
        assert len(mail.outbox) == 2

    def test_a_fresh_queued_send_does_not_touch_retry_count(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        """retry_count means "has this failed and been retried" - a row's first attempt is not
        a retry of anything, however long it happened to sit in the queue first.
        """
        candidate = make_candidate(make_batch(ta_user), ta_user)
        invitation = make_invitation(candidate, ta_user)

        call_command('process_email_queue')

        invitation.refresh_from_db()
        assert invitation.retry_count == 0
        assert invitation.email_status == Invitation.EmailStatus.SENT

    def test_a_retried_failure_has_its_retry_count_incremented(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        candidate = make_candidate(make_batch(ta_user), ta_user)
        invitation = make_invitation(candidate, ta_user,
                                     email_status=Invitation.EmailStatus.FAILED)
        assert invitation.retry_count == 0

        call_command('process_email_queue', '--include-failed')

        invitation.refresh_from_db()
        assert invitation.retry_count == 1

    def test_a_row_at_the_retry_limit_is_left_alone(
        self, ta_user, make_batch, make_candidate, make_invitation, settings
    ):
        """Without this ceiling a permanently bad address would be re-attempted by every
        scheduled run forever, for a cause the worker itself can never fix.
        """
        settings.INVITE_MAX_RETRY_ATTEMPTS = 3
        candidate = make_candidate(make_batch(ta_user), ta_user)
        invitation = make_invitation(candidate, ta_user,
                                     email_status=Invitation.EmailStatus.FAILED)
        Invitation.objects.filter(pk=invitation.pk).update(retry_count=3)

        call_command('process_email_queue', '--include-failed')

        invitation.refresh_from_db()
        assert invitation.retry_count == 3
        assert mail.outbox == []

    def test_ignore_retry_limit_overrides_the_cap(
        self, ta_user, make_batch, make_candidate, make_invitation, settings
    ):
        settings.INVITE_MAX_RETRY_ATTEMPTS = 3
        candidate = make_candidate(make_batch(ta_user), ta_user)
        invitation = make_invitation(candidate, ta_user,
                                     email_status=Invitation.EmailStatus.FAILED)
        Invitation.objects.filter(pk=invitation.pk).update(retry_count=3)

        call_command('process_email_queue', '--include-failed', '--ignore-retry-limit')

        invitation.refresh_from_db()
        assert invitation.retry_count == 4
        assert len(mail.outbox) == 1

    def test_sends_within_one_run_are_paced(
        self, ta_user, make_batch, make_candidate, make_invitation, settings, monkeypatch
    ):
        settings.INVITE_SEND_DELAY_SECONDS = 2.5
        batch = make_batch(ta_user)
        for _ in range(3):
            make_invitation(make_candidate(batch, ta_user), ta_user)
        sleeps = []
        monkeypatch.setattr(
            'api.management.commands.process_email_queue.time.sleep', sleeps.append,
        )

        call_command('process_email_queue')

        # Between sends, not before the first or after the last: 3 invitations -> 2 gaps.
        assert sleeps == [2.5, 2.5]

    def test_a_row_already_claimed_by_a_concurrent_run_is_skipped_not_resent(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        """The concurrency-safety property that makes this command safe to run from more than
        one App Service instance at once (see the command's own module docstring): the
        eligibility check is repeated under the row lock, so a row another process already
        finished between this run reading its `pending` list and reaching this row is skipped
        rather than sent a second time.
        """
        from api.management.commands.process_email_queue import Command

        candidate = make_candidate(make_batch(ta_user), ta_user)
        invitation = make_invitation(candidate, ta_user)
        # Simulates a concurrent run having already sent it in the gap between this command
        # building its `pending` list and reaching this specific row.
        invitation.email_status = Invitation.EmailStatus.SENT
        invitation.save(update_fields=['email_status'])

        outcome = Command()._send_one_locked(invitation, 'https://exam.example.test')

        assert outcome == 'skipped'
        assert mail.outbox == []


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

    def test_the_contact_email_is_whoever_actually_sent_the_invite(
        self, ta_user, admin_user, make_batch, make_candidate, make_invitation, settings
    ):
        """A candidate with a problem should be able to reach the actual person who invited
        them, not a shared inbox nobody reads - whether that person is a TA or an admin.
        """
        settings.SUPPORT_EMAIL = 'shared-inbox@accelirate.com'
        invitation = make_invitation(
            make_candidate(make_batch(ta_user), ta_user), sent_by=admin_user,
        )

        invites.send_invite_and_record(invitation, 'https://exam.example.test')

        body = mail.outbox[0].body
        assert admin_user.email in body
        assert 'shared-inbox@accelirate.com' not in body

    def test_falls_back_to_the_shared_inbox_if_the_sender_account_is_gone(
        self, ta_user, make_batch, make_candidate, make_invitation, settings
    ):
        """Invitation.sent_by is SET_NULL, so a deleted staff account must not leave the
        candidate with no way to ask for help at all.
        """
        settings.SUPPORT_EMAIL = 'shared-inbox@accelirate.com'
        invitation = make_invitation(
            make_candidate(make_batch(ta_user), ta_user), sent_by=None,
        )

        invites.send_invite_and_record(invitation, 'https://exam.example.test')

        assert 'shared-inbox@accelirate.com' in mail.outbox[0].body

    def test_the_seb_config_link_is_a_real_clickable_anchor_in_the_html(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        """A plain https:// URL, not the seb:// launch scheme - see
        render_invitation_email's own docstring for why only this one is safe to put in an
        email. _linkify auto-links any bare https:// URL in the body, so this needs no special
        cta_url-style handling to become clickable.
        """
        invitation = make_invitation(make_candidate(make_batch(ta_user), ta_user), ta_user)

        invites.send_invite_and_record(invitation, 'https://exam.example.test')

        expected_url = (
            'https://exam.example.test/api/exam/token/%s/seb-config/'
            % invitation.unique_link_token
        )
        html = mail.outbox[0].alternatives[0][0]
        assert f'<a href="{expected_url}"' in html
        assert 'seb://' not in html

    def test_the_seb_config_link_survives_in_the_plain_text_part(
        self, ta_user, make_batch, make_candidate, make_invitation
    ):
        invitation = make_invitation(make_candidate(make_batch(ta_user), ta_user), ta_user)

        invites.send_invite_and_record(invitation, 'https://exam.example.test')

        expected_url = (
            'https://exam.example.test/api/exam/token/%s/seb-config/'
            % invitation.unique_link_token
        )
        assert expected_url in mail.outbox[0].body


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
