import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from api.models import User


class Command(BaseCommand):
    """Reset an existing account's password from the terminal.

    The password is read via getpass rather than taken as an argument, so it never lands in
    shell history, process listings, or CI logs the way `--password` on create_admin_user does.
    """
    help = "Reset a TalentGate account's password (prompts for the new password)."

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)
        parser.add_argument(
            '--no-force-change', action='store_true',
            help="Don't require the holder to replace this password at next login. Only "
                 "correct when you are resetting your own account.",
        )

    def handle(self, *args, **options):
        email = options['email'].strip().lower()

        try:
            user = User.objects.get(email__iexact=email, is_deleted=False)
        except User.DoesNotExist:
            raise CommandError(f'No active account found for {email}.')

        self.stdout.write(
            f'Resetting password for {user.full_name} <{user.email}> '
            f'(role: {user.role.role_code})'
        )
        self.stdout.write(self.style.WARNING(f'Target database: {user._state.db} '
                                             f'- make sure this is the environment you mean.'))

        password = getpass.getpass('New password: ')
        if password != getpass.getpass('Confirm new password: '):
            raise CommandError('Passwords did not match.')

        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError('Password does not meet requirements: ' + ' '.join(exc.messages))

        user.set_password(password)
        # Whoever ran this command now knows the account's password. Unless they ARE the account
        # holder, that is a handover credential, and the holder should replace it before the
        # account is usable - same reasoning as the emailed temp password in
        # services/user_provisioning.py. --no-force-change is for the self-reset case.
        user.must_change_password = not options['no_force_change']
        user.save()

        self.stdout.write(self.style.SUCCESS(f'Password updated for {user.email}.'))
        if user.must_change_password:
            self.stdout.write(
                'They will be asked to set their own password at next login, and staff '
                'endpoints stay closed to them until they do. Pass --no-force-change to skip '
                'that (e.g. when resetting your own account).'
            )
