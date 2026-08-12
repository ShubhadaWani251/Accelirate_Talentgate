from django.conf import settings


def is_corporate_email(email):
    domain = email.rsplit('@', 1)[-1].lower()
    return domain in settings.CORPORATE_EMAIL_DOMAINS
