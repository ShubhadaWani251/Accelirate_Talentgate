import re

from django.core.exceptions import ValidationError


class ComplexityValidator:
    """Plugs into AUTH_PASSWORD_VALIDATORS - requires a mix of character classes,
    not just length. Supersedes Django's built-in MinimumLengthValidator (see
    config/settings.py) since it enforces its own, stricter minimum.
    """

    def __init__(self, min_length=10):
        self.min_length = min_length

    def validate(self, password, user=None):
        errors = []
        if len(password) < self.min_length:
            errors.append(f'Password must be at least {self.min_length} characters long.')
        if not re.search(r'[A-Z]', password):
            errors.append('Password must contain at least one uppercase letter.')
        if not re.search(r'[a-z]', password):
            errors.append('Password must contain at least one lowercase letter.')
        if not re.search(r'[0-9]', password):
            errors.append('Password must contain at least one digit.')
        if not re.search(r'[^A-Za-z0-9]', password):
            errors.append('Password must contain at least one special character (e.g. !@#$%^&*).')
        if errors:
            raise ValidationError(errors)

    def get_help_text(self):
        return (
            f'Your password must be at least {self.min_length} characters and include an '
            'uppercase letter, a lowercase letter, a digit, and a special character.'
        )
