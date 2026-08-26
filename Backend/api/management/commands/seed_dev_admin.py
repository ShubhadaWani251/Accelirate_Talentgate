from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from api.models import Role, User

# A fixed credential is only safe because this command refuses to run against anything
# but a local database - see _require_local_database. Changing that guard turns this
# into a published Administrator password for whatever environment it is pointed at.
DEV_EMAIL = 'dev-admin@accelirate.com'
DEV_PASSWORD = 'Thicket#Marlow7'
DEV_FIRST_NAME = 'Local'
DEV_LAST_NAME = 'Developer'

LOCAL_HOSTS = {'', 'localhost', '127.0.0.1', '::1'}


class Command(BaseCommand):
    """Create (or restore) a known Administrator account for local development.

    Nothing about this is safe to run against a shared environment, so the guard below is
    the point of the command rather than an afterthought: staging and production hold real
    candidate data, and a documented password would be a full bypass of the app's own RBAC
    for anyone who can read this file.
    """

    help = ('Create a local-development Administrator with a known password. '
            'Refuses to run against a non-local database.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--email', default=DEV_EMAIL,
            help=f'Override the seeded address (default: {DEV_EMAIL}).',
        )
        parser.add_argument(
            '--password', default=DEV_PASSWORD,
            help='Override the seeded password. Must still satisfy the app validators.',
        )

    def handle(self, *args, **options):
        self._require_local_database()

        email = options['email'].strip().lower()
        password = options['password']

        try:
            admin_role = Role.objects.get(role_code='admin')
        except Role.DoesNotExist:
            raise CommandError(
                "Role 'admin' not found - load fixtures first: "
                'python manage.py loaddata fixtures/initial_roles.json'
            )

        user = User.objects.filter(email__iexact=email).first()

        # validate_password compares against the user's own attributes, so it needs the
        # instance the password will actually belong to - not the one already in the table.
        candidate = user or User(
            first_name=DEV_FIRST_NAME, last_name=DEV_LAST_NAME, email=email, role=admin_role,
        )
        try:
            validate_password(password, candidate)
        except ValidationError as exc:
            raise CommandError('Password does not meet requirements: ' + ' '.join(exc.messages))

        if user is None:
            candidate.is_active = True
            candidate.is_deleted = False
            candidate.set_password(password)
            candidate.save()
            action = 'created'
        else:
            # Re-runnable on purpose: the usual reason to invoke this is having lost access
            # to a local database that already has the account.
            user.role = admin_role
            user.is_active = True
            user.is_deleted = False
            user.set_password(password)
            user.save()
            action = 'reset'

        self.stdout.write(self.style.SUCCESS(f'Administrator {action}: {email}'))
        self.stdout.write(f'Password: {password}')
        self.stdout.write(self.style.WARNING(
            'Local development only. This password is in source control.'
        ))

    def _require_local_database(self):
        db = connection.settings_dict
        engine = db.get('ENGINE', '')
        host = (db.get('HOST') or '').strip().lower()

        if 'sqlite' in engine:
            return
        if host in LOCAL_HOSTS:
            return

        raise CommandError(
            f'Refusing to seed a known password into a non-local database '
            f'(host={host or "<unset>"}, name={db.get("NAME")}). '
            'This command is for local development only; use create_admin_user for any '
            'shared environment so the password is chosen per-environment and never '
            'committed.'
        )
