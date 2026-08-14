from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError

from api.services.graph_email import GraphEmailError, _token_cache


class Command(BaseCommand):
    """Check the Microsoft Graph mail setup end to end.

    Separates the two things that can be wrong - the app registration/credentials, and
    permission to send as the chosen mailbox - so a failure points at one of them rather than
    just "email didn't work".
    """
    help = 'Verify Microsoft Graph email configuration, optionally sending a test message.'

    def add_arguments(self, parser):
        parser.add_argument('--to', help='Send a test email to this address.')

    def handle(self, *args, **options):
        self.stdout.write('Configuration:')
        for name in ('EMAIL_BACKEND', 'GRAPH_TENANT_ID', 'GRAPH_CLIENT_ID',
                     'GRAPH_SENDER', 'DEFAULT_FROM_EMAIL'):
            self.stdout.write(f'   {name:22} {getattr(settings, name, "") or "(unset)"}')
        # Never print the secret - only whether one is present.
        secret = getattr(settings, 'GRAPH_CLIENT_SECRET', '')
        self.stdout.write(f'   {"GRAPH_CLIENT_SECRET":22} '
                          f'{"set (" + str(len(secret)) + " chars)" if secret else "(unset)"}')

        self.stdout.write('\nStep 1 - requesting an access token...')
        try:
            token = _token_cache.get()
        except GraphEmailError as exc:
            raise CommandError(f'Token request failed: {exc}')
        self.stdout.write(self.style.SUCCESS(f'   OK - token acquired ({len(token)} chars)'))

        if not options['to']:
            self.stdout.write('\nCredentials look good. Re-run with --to you@accelirate.com '
                              'to confirm the mailbox can actually send.')
            return

        self.stdout.write(f'\nStep 2 - sending a test message to {options["to"]}...')
        try:
            sent = send_mail(
                subject='Accelirate TalentGate - Graph email test',
                message='If you are reading this, TalentGate can send mail through '
                        'Microsoft Graph. No action needed.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[options['to']],
                fail_silently=False,
            )
        except GraphEmailError as exc:
            raise CommandError(
                f'Send failed: {exc}\n\n'
                f'If this mentions ErrorAccessDenied, the app registration is missing the '
                f'Mail.Send APPLICATION permission (not delegated), or admin consent has not '
                f'been granted, or GRAPH_SENDER is not a mailbox this app may send as.'
            )
        self.stdout.write(self.style.SUCCESS(f'   OK - Graph accepted {sent} message(s).'))
        self.stdout.write('\nCheck the inbox. Delivery is asynchronous, so give it a minute.')
