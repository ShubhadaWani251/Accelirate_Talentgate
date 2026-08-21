"""Proves the harness works and, most importantly, that it cannot reach a real database.

test_test_database_is_isolated is a guard, not a formality. It already caught a real problem: an
earlier version of this suite overrode DATABASES from a conftest hook, which was too late -
pytest-django had already cached the connection, so the suite would have created and dropped
test_QA_TalentDB on the shared PostgreSQL server. If this test ever fails, stop and check where
the suite is pointed before running anything else.
"""

from django.conf import settings
from django.db import connection


def test_test_database_is_isolated():
    assert settings.DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3'
    # Django rewrites the in-memory name to its shared form
    # (file:memorydb_default?mode=memory&cache=shared) so several connections in one process see
    # the same database. Asserting on 'memory' rather than the literal ':memory:' keeps this
    # checking the property that matters - never touching a file or a server - instead of an
    # implementation detail of Django's SQLite backend.
    name = str(settings.DATABASES['default']['NAME'])
    assert 'memory' in name, name

    # The live connection, not just the settings dict. That distinction is precisely what the
    # earlier bug turned on: ENGINE had been overridden while the cached connection still carried
    # the real database's name.
    assert connection.settings_dict['ENGINE'] == 'django.db.backends.sqlite3'
    assert 'memory' in str(connection.settings_dict['NAME'])
    assert 'TalentDB' not in str(connection.settings_dict['NAME'])


def test_email_cannot_leave_the_process():
    from django.core import mail
    mail.send_mail('subject', 'body', 'from@example.test', ['to@example.test'])
    assert len(mail.outbox) == 1
    assert 'locmem' in settings.EMAIL_BACKEND


def test_fixtures_build_a_full_object_graph(ta_user, make_batch, make_candidate, make_invitation):
    batch = make_batch(ta_user)
    candidate = make_candidate(batch, ta_user)
    invitation = make_invitation(candidate, ta_user)
    assert invitation.batch_id == batch.batch_id
    assert candidate.aadhaar_last4 == '1234'
