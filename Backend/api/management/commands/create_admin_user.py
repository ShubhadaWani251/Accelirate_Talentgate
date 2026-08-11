from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from api.models import Role, User


class Command(BaseCommand):
    help = 'Bootstrap an initial Administrator account for TalentGate.'

    def add_arguments(self, parser):
        parser.add_argument('--first-name', required=True)
        parser.add_argument('--last-name', required=True)
        parser.add_argument('--email', required=True)
        parser.add_argument('--password', required=True)

    def handle(self, *args, **options):
        email = options['email'].strip().lower()

        try:
            admin_role = Role.objects.get(role_code='admin')
        except Role.DoesNotExist:
            raise CommandError(
                "Role 'admin' not found - load fixtures first: "
                "python manage.py loaddata fixtures/initial_roles.json"
            )

        if User.objects.filter(email__iexact=email).exists():
            raise CommandError(f'A user with email {email} already exists.')

        try:
            validate_password(options['password'])
        except ValidationError as exc:
            raise CommandError('Password does not meet requirements: ' + ' '.join(exc.messages))

        user = User(
            first_name=options['first_name'],
            last_name=options['last_name'],
            email=email,
            role=admin_role,
            is_active=True,
        )
        user.set_password(options['password'])
        user.save()

        self.stdout.write(self.style.SUCCESS(f'Administrator created: {email}'))
