"""Settings used by the test suite. Selected via DJANGO_SETTINGS_MODULE in pytest.ini.

This exists to make it structurally impossible for the suite to touch a real database.

The real DATABASES points at a shared PostgreSQL instance holding live candidate data. Django's
test runner does not use that database directly - it creates test_<name> alongside it and drops
it at teardown - but that is still a create-and-drop against a production-adjacent server,
triggered by nothing more than having the wrong .env loaded when running pytest.

Overriding DATABASES from a conftest hook was tried first and is not sufficient: by the time any
conftest runs, pytest-django has already initialised Django and the connection handler has cached
the original settings_dict, so the override changed ENGINE but the test database name was still
derived from the real one. A settings module is read before any connection exists, so there is no
ordering to get wrong.
"""

from .settings import *  # noqa: F401,F403

# In-memory SQLite. Fast, isolated per test process, and nothing to clean up. The schema is built
# directly from the models (pytest.ini passes --no-migrations) because migration 0013 contains
# PostgreSQL-only SQL.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
        'TEST': {'NAME': ':memory:'},
    }
}

# DRF's APIClient sends requests to the host 'testserver'. Without this, CommonMiddleware rejects
# every request with a 400 before any view runs, and every API test fails for a reason that has
# nothing to do with the code under test.
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']

# Email must never leave the test process. locmem collects messages in django.core.mail.outbox so
# tests can assert on what was sent.
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
DEFAULT_FROM_EMAIL = 'noreply@accelirate.com'
SUPPORT_EMAIL = 'support@accelirate.com'

# Fixed, so tests asserting on generated assessment links do not depend on a developer's .env.
FRONTEND_ORIGIN = 'https://exam.example.test'

# No real cloud storage. Tests that exercise evidence URL signing set this themselves.
AZURE_STORAGE_CONNECTION_STRING = ''

# Rate-limit and login-lockout counters live in the cache. Per-process locmem is right for tests;
# the clear_cache fixture in conftest empties it around each one so counts cannot leak between
# tests and make them order-dependent.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

# Never send test errors to a real Sentry project, whatever the environment has set.
SENTRY_DSN = ''

# Password hashing dominates the runtime of any test that creates a user with a usable password.
# MD5 is obviously unsuitable for anything real and is used here only because it is fast.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Quiet during tests: the suite deliberately exercises failure paths that log exceptions, and
# those tracebacks would otherwise bury the actual test output.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'null': {'class': 'logging.NullHandler'}},
    'root': {'handlers': ['null'], 'level': 'CRITICAL'},
    'loggers': {
        'api': {'handlers': ['null'], 'level': 'CRITICAL', 'propagate': False},
        'django': {'handlers': ['null'], 'level': 'CRITICAL', 'propagate': False},
    },
}

DEBUG = False
